"""Skill bank loader: validation, atom index, lazy mtime-cached retrieval.

The bank (``data/cv_baseline.json``) is a SEPARATE matching source from the
live CV — see plan in docs/decisions.md. Tailoring reads only the top-level
``skills`` list; ``deferred`` is the operator's parking lot, never offered to
a recruiter, but gap analysis reads it to answer "you parked this and N jobs
want it".
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
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
# `_note` is the operator's reason for parking a deferred skill ("Last
# professional use unclear…") — gap analysis surfaces it, so it must survive
# the projection in _validate_atom. Present on only some atoms.
#
# `last_used` and `confidence` model interview-readiness, which `level` cannot:
# `level` is depth-at-peak ("I was middle at this"), not readiness today. A
# skill used for one month a year ago is `basic` and sits in `skills[]`, so
# tailoring would put it in front of a recruiter — while refreshing it costs
# nearly as much as learning something new. Both fields are optional; an atom
# with neither is treated as current.
ATOM_OPTIONAL_KEYS = ("aliases", "presentation", "_note", "last_used", "confidence")

# `confidence` overrides any `last_used` inference, because decay is not
# uniform: six months off SQL costs nothing, six months off Kubernetes is real.
CONFIDENCE_CURRENT = "current"  # interviewable today
CONFIDENCE_REFRESH = "needs_refresh"  # listed, but would need study first
CONFIDENCE_LEVELS = {CONFIDENCE_CURRENT, CONFIDENCE_REFRESH}

# Atoms unused for longer than this are stale unless `confidence` says otherwise.
STALE_AFTER_MONTHS = 18


# "2024" or "2024-06". Day precision would imply a certainty nobody has about
# when they last touched a tool.
_LAST_USED_RE = re.compile(r"\d{4}(-\d{2})?")


class BaselineError(ValueError):
    """The skill bank file is missing, malformed, or violates the schema."""


def is_stale(atom: dict[str, Any], *, today: date | None = None) -> bool:
    """True when *atom* is on the CV but would need study before an interview.

    `confidence` is authoritative when set, because decay is not uniform —
    six months away from SQL costs nothing, six months away from Kubernetes
    is real. Otherwise `last_used` older than ``STALE_AFTER_MONTHS`` marks it
    stale. An atom with neither field is treated as current: the operator has
    not said otherwise, and guessing would flag the whole bank.
    """
    confidence = atom.get("confidence")
    if confidence == CONFIDENCE_REFRESH:
        return True
    if confidence == CONFIDENCE_CURRENT:
        return False

    last_used = atom.get("last_used")
    if not last_used:
        return False
    parts = str(last_used).split("-")
    year, month = int(parts[0]), int(parts[1]) if len(parts) > 1 else 12
    now = today or date.today()
    months_since = (now.year - year) * 12 + (now.month - month)
    return months_since > STALE_AFTER_MONTHS


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
    confidence = atom.get("confidence")
    if confidence is not None and confidence not in CONFIDENCE_LEVELS:
        raise BaselineError(
            f"bank atom {name!r} has invalid confidence {confidence!r}; "
            f"expected one of {sorted(CONFIDENCE_LEVELS)}"
        )
    last_used = atom.get("last_used")
    if last_used is not None and not _LAST_USED_RE.fullmatch(str(last_used)):
        raise BaselineError(
            f"bank atom {name!r} has invalid last_used {last_used!r}; "
            "expected 'YYYY' or 'YYYY-MM'"
        )
    return {
        key: atom[key]
        for key in ATOM_REQUIRED_KEYS | set(ATOM_OPTIONAL_KEYS)
        if key in atom
    }


def load_baseline(path: Path, key: str = "skills") -> list[dict[str, Any]]:
    """Parse and validate one atom list from the bank.

    Args:
        path: The skill bank file.
        key: Which top-level list to read — ``"skills"`` (the active atoms) or
            ``"deferred"`` (the operator's parking lot). Both share the atom
            schema, so both validate identically. ``"skills"`` must be present
            and non-empty; any other list may be absent, yielding ``[]``.

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

    return parse_baseline(raw, key)


def parse_baseline(raw: Any, key: str = "skills") -> list[dict[str, Any]]:
    """Validate an already-parsed bank payload, returning one atom list.

    Split from :func:`load_baseline` so a bank read from Postgres validates
    through exactly the same rules as one read from disk.
    """
    if not isinstance(raw, dict):
        raise BaselineError(
            f"Skill bank must be a JSON object, got {type(raw).__name__}"
        )
    entries = raw.get(key)
    # `skills` is the matching source and must exist; `deferred` is the
    # operator's parking lot, and an empty or absent one is a valid bank.
    if entries is None and key != "skills":
        return []
    if not isinstance(entries, list) or (not entries and key == "skills"):
        raise BaselineError(f"Skill bank must have a non-empty {key!r} list")

    atoms = [_validate_atom(atom) for atom in entries]
    names = [atom["atom"] for atom in atoms]
    if len(names) != len(set(names)):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise BaselineError(f"Skill bank has duplicate atoms: {dupes}")
    return atoms


def validate_bank_payload(kind: str, payload: Any) -> None:
    """Raise :class:`BaselineError` if *payload* is unusable for *kind*.

    Used on write (documents API) so a document that would break matching is
    rejected before it reaches storage, rather than on every later read.
    """
    if kind == "jd_vocabulary":
        terms = payload.get("terms") if isinstance(payload, dict) else None
        if not isinstance(terms, list) or not terms:
            raise BaselineError("JD vocabulary must have a non-empty 'terms' list")
        for entry in terms:
            if not isinstance(entry, dict) or not str(entry.get("term", "")).strip():
                raise BaselineError(f"Vocabulary entry missing a 'term': {entry!r}")
        return
    # Skill bank: both lists must validate, and `deferred` may be absent.
    parse_baseline(payload, "skills")
    parse_baseline(payload, "deferred")


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


_cache: dict[tuple[str, str, int, int], list[dict[str, Any]]] = {}


def get_baseline(path: Path | None = None, key: str = "skills") -> list[dict[str, Any]]:
    """Lazy, mtime-cached access to one bank atom list.

    The resolved path follows ``settings.cv_baseline_path``. Memoization is
    keyed by (path, key, size, mtime_ns), so editing the bank file is picked
    up on the next tailoring call without a server restart — the same
    generation-checked hot-reload spirit as CvSource. ``key`` is part of the
    cache key so ``"skills"`` and ``"deferred"`` never alias each other.
    """
    if path is None:
        from services.portfolio.settings import settings

        path = settings.cv_baseline_path
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise BaselineError(f"Skill bank file not found: {path}") from None

    cache_key = (str(path), key, stat.st_size, stat.st_mtime_ns)
    cached = _cache.get(cache_key)
    if cached is None:
        cached = load_baseline(path, key)
        _cache[cache_key] = cached
    return cached
