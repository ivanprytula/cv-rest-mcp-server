"""Answer "what should I learn next?" for one job description.

Every term a JD demands lands in exactly one of four tiers, ordered by how
much work it would take to claim the skill:

===========  ==========================================================
covered      On the live CV. Nothing to do.
unvouched    In the skill bank, but the live CV does not claim it —
             the trust policy drops these, so a recruiter never sees
             them. Cheapest gap to close: update the CV.
deferred     Parked in the bank's ``deferred`` list, often with a note
             explaining why. Closing it is a decision, not study.
unknown      In the JD vocabulary but nowhere in the bank. This is the
             real "go learn it" tier.
===========  ==========================================================

The partition holds *by construction*: one merged index maps each term to
one tier, so a term cannot be counted twice or missed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from services.portfolio.matching.baseline import BaselineError
from services.portfolio.matching.matcher import LEVEL_STRENGTH
from services.portfolio.matching.normalize import normalize_jd_text
from services.portfolio.matching.parser import extract_mentions
from services.portfolio.matching.taxonomy import build_skill_index, normalize_skill


Tier = Literal["covered", "unvouched", "deferred", "unknown"]

# Ordered cheapest-to-close first; also the display order on the report.
TIERS: tuple[Tier, ...] = ("covered", "unvouched", "deferred", "unknown")


@dataclass(frozen=True)
class SkillGap:
    """One JD requirement, resolved to a tier.

    ``required_level`` is the level the JD asked for (``None`` = no
    qualifier). ``bank_level`` is what the skill bank claims, absent for
    unknown terms. ``note`` carries the operator's reason for parking a
    deferred skill. ``evidence`` is the JD phrase that produced the mention,
    so a surprising verdict can be audited against the source text.
    """

    term: str
    tier: Tier
    group_id: str
    required_level: str | None = None
    bank_level: str | None = None
    note: str | None = None
    evidence: str = ""


@dataclass(frozen=True)
class GapReport:
    """Every requirement found in one JD, split by tier."""

    gaps: tuple[SkillGap, ...]

    def by_tier(self, tier: Tier) -> tuple[SkillGap, ...]:
        return tuple(gap for gap in self.gaps if gap.tier == tier)

    @property
    def coverage(self) -> float:
        """Share of requirements already on the live CV (0.0-1.0)."""
        if not self.gaps:
            return 1.0
        return len(self.by_tier("covered")) / len(self.gaps)


def load_vocabulary(path: Path) -> list[dict[str, Any]]:
    """Parse the JD-side vocabulary.

    Entries are ``{term, group_id, aliases?}`` — deliberately not the bank's
    atom schema, since a vocabulary term need not be a skill the operator
    has. Returns atom-shaped dicts so :func:`build_atom_index` can index them
    unchanged.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BaselineError(f"JD vocabulary file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BaselineError(f"JD vocabulary is not valid JSON ({path}): {exc}") from exc

    terms = raw.get("terms") if isinstance(raw, dict) else None
    if not isinstance(terms, list) or not terms:
        raise BaselineError(f"JD vocabulary {path} must have a non-empty 'terms' list")

    return [
        {
            "atom": entry["term"],
            "group_id": entry.get("group_id", ""),
            "aliases": entry.get("aliases", []),
        }
        for entry in terms
    ]


def _tier_index(
    bank_atoms: list[dict[str, Any]],
    deferred_atoms: list[dict[str, Any]],
    vocabulary: list[dict[str, Any]],
    live_cv: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Map every known term to exactly one tier.

    Precedence runs cheapest-to-close first: a term on the live CV is
    ``covered`` even though it is also a bank atom, and a bank atom outranks
    the same word in the vocabulary. Because each key is written once, the
    four tiers are disjoint and exhaustive by construction — no post-hoc
    de-duplication, and no term can be silently double-counted.
    """
    live_index = build_skill_index(
        live_cv.get("skills", []), live_cv.get("additional_skills")
    )

    merged: dict[str, dict[str, Any]] = {}

    # Widest first, so narrower tiers overwrite: vocabulary < deferred < bank.
    for atom in vocabulary:
        key = normalize_skill(atom["atom"])
        if key:
            merged.setdefault(key, {**atom, "_tier": "unknown"})

    for atom in deferred_atoms:
        for key in _atom_keys(atom):
            merged[key] = {**atom, "_tier": "deferred"}

    for atom in bank_atoms:
        tier = "covered" if normalize_skill(atom["atom"]) in live_index else "unvouched"
        for key in _atom_keys(atom):
            merged[key] = {**atom, "_tier": tier}

    return merged


def _atom_keys(atom: dict[str, Any]) -> list[str]:
    """Canonical key plus alias keys for one atom."""
    keys = [normalize_skill(atom["atom"])]
    keys.extend(normalize_skill(alias) for alias in atom.get("aliases", []))
    return [key for key in keys if key]


def _is_stronger(candidate: str | None, current: str | None) -> bool:
    """True when *candidate* states a firmer level than *current*.

    ``None`` means the JD stated no qualifier, which is weakest — so any
    qualified mention replaces a bare one regardless of which came first.
    """
    return LEVEL_STRENGTH.get(candidate, 0) > LEVEL_STRENGTH.get(current, 0)


def detect_gaps(
    jd_text: str,
    bank_atoms: list[dict[str, Any]],
    deferred_atoms: list[dict[str, Any]],
    vocabulary: list[dict[str, Any]],
    live_cv: dict[str, Any],
) -> GapReport:
    """Resolve every requirement in *jd_text* to a tier.

    Args:
        jd_text: Raw job-description text; normalised here, so callers need
            not pre-clean it.
        bank_atoms: The bank's active ``skills`` atoms.
        deferred_atoms: The bank's ``deferred`` atoms.
        vocabulary: JD-side terms from :func:`load_vocabulary`.
        live_cv: The operator's public CV, defining the ``covered`` tier.

    Returns:
        A :class:`GapReport` whose gaps are unique by term and ordered by
        tier (cheapest to close first), then alphabetically.
    """
    index = _tier_index(bank_atoms, deferred_atoms, vocabulary, live_cv)
    normalized = normalize_jd_text(jd_text)

    # Strongest mention wins, in either order: "Kubernetes … expert Kubernetes"
    # and "expert Kubernetes … Kubernetes" both record `expert`.
    best: dict[str, SkillGap] = {}
    for mention in extract_mentions(normalized, index):
        entry = index[mention.skill]
        term = entry["atom"]
        existing = best.get(term)
        if existing is not None and not _is_stronger(
            mention.level, existing.required_level
        ):
            continue
        best[term] = SkillGap(
            term=term,
            tier=entry["_tier"],
            group_id=entry.get("group_id", ""),
            required_level=mention.level,
            bank_level=entry.get("level"),
            note=entry.get("_note"),
            evidence=mention.raw,
        )

    gaps = sorted(best.values(), key=lambda g: (TIERS.index(g.tier), g.term.lower()))
    return GapReport(gaps=tuple(gaps))
