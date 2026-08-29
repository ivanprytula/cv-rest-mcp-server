#!/usr/bin/env python3
"""Print a TAILOR_BEARER_TOKEN without visually-confusable characters (0O1lI5S2Z)."""

import secrets
from string import ascii_lowercase, ascii_uppercase, digits


_EXCLUDE = "0O1lI5S2Z"
_ALPHABET = "".join(
    c for c in ascii_uppercase + ascii_lowercase + digits if c not in _EXCLUDE
)


def gen_token(length: int = 48) -> str:
    """Sample *length* independent characters from the unambiguous alphabet."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


if __name__ == "__main__":
    print(gen_token())
