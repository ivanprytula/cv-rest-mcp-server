"""Refresh-token family service with reuse-detection (ADR-022, Postgres-backed).

Revocation model for stateless JWTs: the access token cannot be revoked
instantly, so we rely on a short TTL plus refresh rotation. A refresh token
identifies its "family"; rotating advances the family's current token on every
successful refresh. Presenting a previously-issued but now non-current token
means it was replayed, which revokes the ENTIRE family — the defense against
stolen refresh tokens.

Replaces the in-memory `RefreshTokenStore` (Phase 2, ADR-023): families now
survive a restart and are shared across instances, so rotation stays correct
when Cloud Run scales past one container.

Unlike `RevisionService`, this service does NOT degrade-don't-crash. A DB
error propagates rather than returning a "not valid" sentinel: silently
treating an outage as a successful auth decision would bypass replay
detection, and treating it as a failed one is what propagating already does.
Fail closed, loudly.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from services.portfolio.auth.refresh_token_repository import RefreshTokenRepository


class RefreshTokenService:
    """Application service orchestrating refresh-token families.

    Depends on the `RefreshTokenRepository` Protocol, not a concrete
    implementation, mirroring `UserService`/`RevisionService`.
    """

    def __init__(self, repo: RefreshTokenRepository) -> None:
        self._repo = repo

    async def create_family(self, first_hash: str, subject: str) -> str:
        """Register a new family whose current token is *first_hash*.

        Returns the family_id (== first_hash). Raises ValueError if the hash is
        already registered (should not happen with random tokens).
        """
        try:
            await self._repo.create_family(family_id=first_hash, subject=subject)
        except IntegrityError as exc:
            raise ValueError("refresh token family already exists") from exc
        return first_hash

    async def rotate(self, presented_hash: str, new_hash: str) -> str | None:
        """Attempt a rotation; returns the family's subject on success.

        Returns None on failure: unknown token, revoked family, or replay (a
        previously-issued but now-rotated token), the last of which revokes the
        whole family.
        """
        family = await self._repo.get_family_by_token(presented_hash)
        if family is None or family.revoked:
            return None
        if presented_hash != family.current_hash:
            # Replay: this hash was valid before but has rotated away.
            await self._repo.revoke(family.family_id)
            return None
        subject = family.subject
        rotated = await self._repo.rotate(
            family_id=family.family_id,
            presented_hash=presented_hash,
            new_hash=new_hash,
        )
        if not rotated:
            # Lost a concurrent race: another request rotated this same token
            # first, so this one is now presenting a stale hash -- a replay by
            # the same rule as above.
            await self._repo.revoke(family.family_id)
            return None
        return subject

    async def is_revoked(self, token_hash: str) -> bool:
        """True if *token_hash* belongs to a revoked family (or is unknown)."""
        family = await self._repo.get_family_by_token(token_hash)
        if family is None:
            return True  # unknown == not usable
        return family.revoked

    async def lookup(self, family_id: str):
        """Return the family row by its id (its first-token hash), if any."""
        return await self._repo.get_family(family_id)

    async def revoke(self, family_id: str) -> None:
        """Revoke a family by id; subsequent refresh attempts fail."""
        await self._repo.revoke(family_id)

    async def revoke_by_token(self, token_hash: str) -> None:
        """Revoke the family that issued *token_hash* (logout)."""
        family = await self._repo.get_family_by_token(token_hash)
        if family is not None:
            await self._repo.revoke(family.family_id)

    async def clear(self) -> None:
        """Drop all families (test helper / lifecycle)."""
        await self._repo.clear()
