"""Level and priority vocabularies shared by the matching pipeline."""

from __future__ import annotations

from typing import Any


# Bank atom level vocabulary mirrors data/cv_baseline.json and parser.Level.
LEVEL_STRENGTH = {"expert": 3, "middle": 2, "basic": 1}
_LEVELS_PRIORITY = {"high": 3, "medium": 2, "low": 1}


def priority_key(atom: dict[str, Any]) -> int:
    """Bank `priority` band as an int for sorting (high=3 … low=1, unknown=0)."""
    return _LEVELS_PRIORITY.get(atom.get("priority"), 0)
