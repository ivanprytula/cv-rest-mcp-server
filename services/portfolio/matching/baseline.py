"""Skill bank loader: validation, atom index, lazy mtime-cached retrieval.

The bank (``data/cv_baseline.json``) is a SEPARATE matching source from the
live CV — see plan in docs/decisions.md. Only the top-level ``skills`` list
is read; ``deferred`` is the operator's parking lot and is never matched.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.portfolio.matching.taxonomy import normalize_skill


logger = logging.getLogger(__name__)

LEVELS = {"expert", "middle", "basic"}
PRIORITIES = {"high", "medium", "low"}

# The display string comes from the bank; the trust policy gates which atoms
# actually reach the tailored output. Required keys mirror the bank schema.
ATOM_REQUIRED_KEYS = {"atom", "group_id", "level", "priority", "category_hint"}

# category_hint encodes "Group > Sub". A hint without the separator cannot be
# mapped onto the output skills structure — fail loud instead of dropping data.
_HINT_SPLIT = " > "

# Extra metadata carried through from the bank (unused by matching today).
ATOM_OPTIONAL_KEYS = ("aliases", "presentation")


class BaselineError(ValueError):
    """The skill bank file is missing, malformed, or violates the schema."""


def _validate_atom(atom: dict[Any, Any]) -> dict[str, Any]:
    missing = ATOM_REQUIRED_KEYS - atom.keys()
    if missing:
        raise BaselineError(
            f"bank atom {atom.get('atom', '?')!r} missing keys {sorted(missing)}"
        )
    name = atom["atom"]
    if not isinstance(name, str) or not name.strip():
        raise BaselineError(f"bank atom has an empty 'atom' value: {atom!r}")
    if name not in (name.strip(),) or len(name) > 60:
        raise BaselineError(
            f"bank atom {name!r} exceeds the 60-char limit or has padding"
        )
    if atom["level"] not in LEVELS:
        raise BaselineError(
            f"bank atom {name!r} has invalid level {atom['level']!r}; expected one of {sorted(LEVELS)}"
        )
    if atom["priority"] not in PRIORITIES:
        raise BaselineError(
            f"bank atom {name!r} has invalid priority {atom['priority']!r}; expected one of {sorted(PRIORITIES)}"
        )
    hint = atom["category_hint"]
    if _HINT_SPLIT not in hint:
        raise BaselineError(
            f"bank atom {name!r} category_hint {hint!r} must be 'Group > Sub'"
        )
    return {
        key: atom[key]
        for key in ATOM_REQUIRED_KEYS | set(ATOM_OPTIONAL_KEYS)
        if key in atom
    }


def load_baseline(path: Path) -> list[dict[str, Any]]:
    """Parse and validate the bank, returning the active atoms (top-level ``skills``).

    Raises :class:`BaselineError` on any schema violation — a broken bank
    aborts a /api/v1/cv/tailor call loudly rather than silently emitting an empty
    or partial skills section.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BaselineError(f"Skill bank file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BaselineError(f"Skill bank is not valid JSON ({path}): {exc}") from exc

    if not isinstance(raw, dict):
        raise BaselineError(
            f"Skill bank must be a JSON object, got {type(raw).__name__}"
        )
    skills = raw.get("skills")
    if not isinstance(skills, list) or not skills:
        raise BaselineError(f"Skill bank {path} must have a non-empty 'skills' list")

    atoms = [_validate_atom(atom) for atom in skills]
    names = [atom["atom"] for atom in atoms]
    if len(names) != len(set(names)):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise BaselineError(f"Skill bank has duplicate atoms: {dupes}")
    return atoms


def build_atom_index(atoms: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a normalized lookup from the active atoms.

    Keys are canonical forms of the atom and its aliases (lowercase), so a
    JD mention like ``"k8s"`` resolves to the ``Kubernetes`` atom via the
    static alias map, and a per-atom alias like ``"claude code cli"`` is
    indexable on its own.

    Canonical names are inserted FIRST: an atom's own name is authoritative,
    so an alias can never shadow a real atom (e.g. an "API security" atom
    aliasing "Casbin" must not hijack the standalone "Casbin" atom).
    Collisions between two aliases resolve first-wins.
    """
    index: dict[str, dict[str, Any]] = {}
    for atom in atoms:
        key = normalize_skill(atom["atom"])
        if key:
            index.setdefault(key, atom)
    for atom in atoms:
        for alias in atom.get("aliases", []):
            key = normalize_skill(alias)
            if key and key not in index:
                index[key] = atom
    return index


_cache: dict[tuple[str, int, int], list[dict[str, Any]]] = {}


def get_baseline(path: Path | None = None) -> list[dict[str, Any]]:
    """Lazy, mtime-cached access to the active bank atoms.

    The resolved path follows ``settings.cv_baseline_path``. Memoization is
    keyed by (path, size, mtime_ns), so editing the bank file is picked up
    on the next tailoring call without a server restart — the same
    generation-checked hot-reload spirit as CvSource.
    """
    if path is None:
        from services.portfolio.settings import settings

        path = settings.cv_baseline_path
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise BaselineError(f"Skill bank file not found: {path}") from None

    key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _cache.get(key)
    if cached is None:
        cached = load_baseline(path)
        _cache[key] = cached
    return cached
