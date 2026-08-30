#!/usr/bin/env python3
"""Generate secure, readable secrets without ambiguous characters (0O1lI5S2Z)."""

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
    print(f"TAILOR_BEARER_TOKEN:  {gen_token(48)}")
    print(f"JWT_SIGNING_KEY:      {gen_token(64)}")
    print(f"REFRESH_TOKEN_PEPPER: {gen_token(32)}")
