#!/usr/bin/env python3
"""Guard routes against leaky error messages and missing auth middleware.

Path-scoped checks that ruff/bandit cannot express — patterns specific to
this codebase's error-handling contract (see AGENTS.md § Code Validation
Rules): error `detail=` strings must never surface exception internals,
and the app's two guarding middlewares must stay wired up in main.py.

`str(exc)` on a domain-specific exception (ValueError from a validator,
PayloadTooLargeError, etc.) is the intended pattern here — the message
itself IS the safe, user-facing detail. Only a bare `Exception`/`OSError`/
`ConnectionError` (system/DB internals) is flagged; those messages can
contain paths, hostnames, or connection strings.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


UNSAFE_EXCEPTION_TYPES = (
    "Exception",
    "OSError",
    "ConnectionError",
    "IOError",
    "SQLAlchemyError",
)

LEAKY_PATTERNS = (
    (
        re.compile(
            r"except\s+(?:" + "|".join(UNSAFE_EXCEPTION_TYPES) + r")\b.*?\bas\s+exc\b"
        ),
        "detail=str(exc)",
        "system/DB exception's message may contain a path, hostname, or connection string",
    ),
    (
        re.compile(
            r'detail\s*=\s*f"[^"]*\{[a-zA-Z_]*(?:path|url|dsn|database_url)[a-zA-Z_]*\}',
            re.IGNORECASE,
        ),
        None,
        "file path / URL / DSN interpolated into a client-facing detail message",
    ),
)


def check_routes_file(path: Path) -> list[str]:
    """Flag `detail=str(exc)` guarded by a broad system/DB exception type."""
    issues = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        for except_pattern, followup, reason in LEAKY_PATTERNS:
            if not except_pattern.search(line):
                continue
            if followup is None:
                issues.append(f"{path}:{lineno}: {reason}\n    {line.strip()}")
                continue
            # The unsafe detail=str(exc) usually appears within the next
            # few lines of the broad except clause that triggered.
            window = "\n".join(lines[lineno - 1 : lineno + 4])
            if followup in window:
                issues.append(f"{path}:{lineno}: {reason}\n    {line.strip()}")
    return issues


REQUIRED_MIDDLEWARE = ("SecurityHeadersMiddleware", "JWTAuthMiddleware")


def check_main_middleware(path: Path) -> list[str]:
    """Verify the two guarding middlewares are still defined and registered."""
    content = path.read_text(encoding="utf-8")
    issues = []
    for name in REQUIRED_MIDDLEWARE:
        if name not in content:
            issues.append(f"{path}: {name} class not found")
        elif f"add_middleware({name})" not in content:
            issues.append(
                f"{path}: {name} defined but never registered via add_middleware()"
            )
    return issues


def main(argv: list[str]) -> int:
    files = [Path(arg) for arg in argv]
    if not files:
        return 0

    issues: list[str] = []
    for path in files:
        if path.name == "main.py":
            issues.extend(check_main_middleware(path))
        if path.name.endswith("routes.py") or path.name == "main.py":
            issues.extend(check_routes_file(path))

    if issues:
        print("\n\n".join(issues))
        print(
            "\nSee AGENTS.md § Code Validation Rules — error `detail=` must stay "
            "generic; log exception internals server-side with logger.exception()."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
