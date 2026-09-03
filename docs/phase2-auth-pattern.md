# Phase 2 Auth Pattern — DB-backed users (async SQLAlchemy + Postgres)

> Status: **built** as Phase 1d (ADR-022), now split by layer across
> `app/auth/user.py` (domain), `user_row.py` (ORM), `user_repository.py`
> (port + adapter), and `user_service.py` (application); the Postgres +
> Alembic swap this doc anticipated has landed (ADR-023). The seam is
> unchanged from the ADR-022 forward path, and patterns are adapted from the
> [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template)
> (MIT).
>
> The goal, restated from ADR-022: keep the swap **local and reversible** — token
> shape (`sub` = username), refresh rotation, and `JWTAuthMiddleware` are UNCHANGED
> by the store. Only the identity→claims derivation at `app/auth/routes.py` and
> the login gate changed, and they now go through `UserService`.

## Identity: username AND email

Unlike the template (which keys on email alone), this project keeps **`username`
as the login identity** and adds **`email`** as a second, unique, contact/
lookup field. The JWT `sub` stays the username. Rationale: the CV service's
existing seams and `/me` already speak `sub = username`; email is additive.

## Boundaries (DDD-flavored, ACROSS-friendly)

- **Domain** — `User` entity (identity + roles, `scopes` derived from roles).
- **Persistence port** — `UserRepository` (ABC) with an async SQLAlchemy
  implementation on Postgres (`asyncpg`). The repo returns a raw `UserRow`
  (which carries `hashed_password`); the domain `User` / `UserRow.to_domain()`
  is what routes see. Schema is Alembic-migrated (`alembic/`), not derived
  from the model via `create_all`.
- **Application service** — `UserService.authenticate()` / `seed_first_admin()`
  orchestrate repo + hasher (the template's `crud.authenticate`, async-native).
- **12-factor** — all config via env in `settings`: `database_url`,
  `first_admin_username/email/password(_file)`.

```python
# app/auth/user.py + user_service.py (abridged, illustrative)
import uuid
from datetime import UTC, datetime

import bcrypt
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class PasswordHasher:
    def hash(self, password):
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def verify(self, password, hashed):
        return bcrypt.checkpw(password.encode(), hashed.encode())


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    email: EmailStr
    is_active: bool
    roles: list[str]

    @property
    def scopes(self) -> list[str]:  # role -> scope mapping (Phase-3 extends)
        base = ["cv:read"]
        if "admin" in self.roles:
            base.append("cv:manage")
        return base


class UserRepository(ABC):
    @abstractmethod
    async def get_by_username(self, username: str) -> UserRow | None: ...
    @abstractmethod
    async def create(self, *, user: UserRow) -> UserRow: ...
```

## Seeding the first user (answers how user #1 gets created)

Borrowed from the template's `init_db()` (env-driven, idempotent, works under
Cloud Run where the first password comes from Secret Manager). `main.py`
lifespan calls `await user_service.init_schema()` then
`await seed_first_admin_from_settings(user_service)`; seeding is skipped when
`first_admin_password` is empty (fail-open on seed, login still fail-closed).

```python
async def seed_first_admin(self, *, username, email, password, roles) -> User | None:
    if not password:
        return None  # nothing configured
    existing = await self._repo.get_by_username(username)
    if existing is not None:
        return existing.to_domain()  # idempotent
    created = await self._repo.create(
        user=UserRow(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=self._hasher.hash(password),
            is_active=True,
            roles=roles,
        )
    )
    return created.to_domain()
```

## Wiring into the seams (no token/middleware change)

1. **Login gate** (`app/auth/routes.py` `token`): `user = await
   user_service.authenticate(body.username, body.password)`; `None` → `401
   Invalid credentials` (same generic message + timing hygiene).
   `user_service` arrives via FastAPI `Depends(get_user_service)`
   (`app.state.user_service`, set once in the app lifespan) so tests swap it
   with `app.dependency_overrides`, not module-patching.
2. **Subject + scopes**: `sign_access_token(user.username, user.scopes)` (roles
   `admin` → `cv:read cv:manage` via `User.scopes`).
3. **Refresh**: unchanged — the family already records its owning subject, so
   refresh re-issues for `user.username` automatically (re-resolved via
   `get_by_username` so an inactive/removed user is rejected).
4. **`/me`**: unchanged (reads `sub` + `scope` from claims).

## Tests

Tests get an isolated store per test: the `user_service` fixture builds a
`SqlAlchemyUserRepository` on a throwaway Postgres database (testcontainers),
seeds the first admin (`operator` / `correct-password` / role `admin`), and
overrides `dependencies.get_user_service` via `app.dependency_overrides`.
Login/refresh/me tests then flow through the seeded store; a handful of
inline tests cover the unconfigured (fail-closed) path against their own
throwaway database.

## What is deliberately NOT copied from the template

- **OAuth2PasswordBearer form login / server-DB-stored refresh / email password
  recovery** — this project uses the `__Host-` httpOnly cookie + in-memory
  rotating `RefreshTokenStore`. Refresh lives outside the DB (Q3 answer), so
  Postgres only stores users, not sessions.
- **Per-request DB lookup in `get_current_user`** — the SPA-heavy read path stays
  stateless (verify JWT, `/me` for freshness). Only login/refresh touch the store.
- **SQLModel / pwdlib / Argon2** — stay on SQLAlchemy 2.0 async + bcrypt.
