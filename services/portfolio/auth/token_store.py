"""In-memory refresh-token family store with reuse-detection.

Revocation model for stateless JWTs (ADR-022): the access token cannot be
revoked instantly, so we rely on a short TTL plus refresh rotation. A refresh
token identifies its "family"; rotating advances the family's current token on
every successful refresh. Presenting a previously-issued but now non-current
token means it was replayed, which revokes the ENTIRE family — the defense
against stolen refresh tokens.

This is an in-memory, single-process store (Phase 2 replaces it with Postgres).
It resets on restart, which is acceptable for the single-operator scale and
short-lived access tokens. A `hash -> family_id` index keeps lookup O(1) after
rotation without scanning every family.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class TokenFamily:
    """State for one refresh-token lineage."""

    family_id: str  # hash of the first (original) refresh token
    subject: str  # the user this family belongs to (re-issued on refresh)
    current_hash: str = ""  # hash of the currently-valid refresh token
    revoked: bool = False


class RefreshTokenStore:
    """Thread-safe map of refresh-token families.

    Families are keyed by `family_id`; a secondary `token_hash -> family_id`
    index (kept in the same lock) resolves any issued token back to its family
    so replay detection works even after the family has rotated.
    """

    def __init__(self) -> None:
        self._families: dict[str, TokenFamily] = {}
        self._index: dict[str, str] = {}  # token_hash -> family_id
        self._lock = threading.Lock()

    def create_family(self, first_hash: str, subject: str) -> str:
        """Register a new family whose current token is *first_hash* for *subject*.

        Returns the family_id (== first_hash). Raises ValueError if the hash is
        already registered (should not happen with random tokens).
        """
        with self._lock:
            if first_hash in self._families:
                raise ValueError("refresh token family already exists")
            family = TokenFamily(
                family_id=first_hash, subject=subject, current_hash=first_hash
            )
            self._families[first_hash] = family
            self._index[first_hash] = first_hash
            return first_hash

    def rotate(self, presented_hash: str, new_hash: str) -> str | None:
        """Attempt a rotation; returns the family's subject on success.

        Returns None on failure: unknown token, revoked family, or replay (a
        previously-issued but now-rotated token), the last of which revokes the
        whole family.
        """
        with self._lock:
            family_id = self._index.get(presented_hash)
            if family_id is None:
                return None
            family = self._families[family_id]
            if family.revoked:
                return None
            if presented_hash != family.current_hash:
                # Replay: this hash was valid before but has rotated away.
                family.revoked = True
                return None
            family.current_hash = new_hash
            self._index[new_hash] = family_id
            return family.subject

    def is_revoked(self, token_hash: str) -> bool:
        """True if *token_hash* belongs to a revoked family (or is unknown)."""
        with self._lock:
            family_id = self._index.get(token_hash)
            if family_id is None:
                return True  # unknown == not usable
            return self._families[family_id].revoked

    def lookup(self, family_id: str) -> TokenFamily | None:
        """Return the family by its id (its first-token hash), if any."""
        with self._lock:
            return self._families.get(family_id)

    def revoke(self, family_id: str) -> None:
        """Revoke a family by id; subsequent refresh attempts fail."""
        with self._lock:
            family = self._families.get(family_id)
            if family is not None:
                family.revoked = True

    def revoke_by_token(self, token_hash: str) -> None:
        """Revoke the family that issued *token_hash* (logout)."""
        with self._lock:
            family_id = self._index.get(token_hash)
            if family_id is not None:
                self._families[family_id].revoked = True

    def clear(self) -> None:
        """Drop all families (test helper / lifecycle)."""
        with self._lock:
            self._families.clear()
            self._index.clear()


token_store = RefreshTokenStore()
