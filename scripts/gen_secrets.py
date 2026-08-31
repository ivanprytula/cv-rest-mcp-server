#!/usr/bin/env python3
"""Generate local-dev auth secrets.

Local auth needs:
  - JWT_SIGNING_KEY: the single shared HS256 secret. A plain random string works
    (no PEM key — HS256 is symmetric, so api-core signs and validates with the
    same value; see ADR-022). One inline .env line, easy to replicate across
    stateless services.
  - REFRESH_TOKEN_PEPPER: random string salted into refresh-token hashes.
  - FIRST_ADMIN_PASSWORD: the first admin's login password (stored in the SQLite
    user store via the env-driven seed at startup, ADR-022 Phase 2) — set it to
    your chosen password in .env; it is NOT hashed here (bcrypt happens at seed).

Print the values for the operator to paste into .env.

Run:  uv run python scripts/gen_secrets.py
"""

import secrets
from string import ascii_lowercase, ascii_uppercase, digits


_EXCLUDE = "0O1lI5S2Z"
_ALPHABET = "".join(
    c for c in ascii_uppercase + ascii_lowercase + digits if c not in _EXCLUDE
)


def gen_token(length: int = 32) -> str:
    """Sample *length* independent characters from the unambiguous alphabet."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


if __name__ == "__main__":
    print(f"JWT_SIGNING_KEY:         {gen_token(64)}")
    print(f"REFRESH_TOKEN_PEPPER:    {gen_token(32)}")
    print("# FIRST_ADMIN_PASSWORD: set this in .env to your first-admin login")
    print(f"#   e.g. FIRST_ADMIN_PASSWORD={gen_token(24)} (change it)")
