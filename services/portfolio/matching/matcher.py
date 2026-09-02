"""Score CV skills against job-description skill requirements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from services.portfolio.matching.taxonomy import normalize_skill


@dataclass(frozen=True)
class SkillMatch:
    """A single matched skill with its score and source information."""

    cv_skill: str
    score: float
    category: str
    sub_category: str


def _substring_score(query: str, token: str) -> float:
    """Containment score via :func:`rapidfuzz.fuzz.partial_ratio` (0-1).

    Finds the highest-scoring window of the longer string — the mature
    replacement for hand-rolled ``in`` probing, with proper token boundaries.
    """
    return fuzz.partial_ratio(query, token) / 100.0


def _fuzzy_score(query: str, token: str) -> float:
    """Full-string similarity via :func:`rapidfuzz.fuzz.ratio` (0-1)."""
    return fuzz.ratio(query, token) / 100.0


# Bank atom level vocabulary mirrors data/cv_baseline.json and parser.Level.
LEVEL_STRENGTH = {"expert": 3, "middle": 2, "basic": 1}
_LEVELS_PRIORITY = {"high": 3, "medium": 2, "low": 1}


def filter_atoms_by_level(
    atoms: list[dict[str, Any]], required_level: str | None
) -> list[dict[str, Any]]:
    """Keep bank atoms whose level meets the JD-required level.

    ``required_level`` is the parser's qualifier verdict; ``None`` means the
    JD stated no qualifier ("no constraint"), so every atom qualifies. On a
    mismatch the atom is rejected, per the plan: a JD demanding expert Python
    must not be answered with a `basic` atom. Result order is stable.
    """
    if required_level is None:
        return list(atoms)
    required_strength = LEVEL_STRENGTH[required_level]
    return [
        atom
        for atom in atoms
        if LEVEL_STRENGTH.get(atom.get("level"), 0) >= required_strength
    ]


def priority_key(atom: dict[str, Any]) -> int:
    """Bank `priority` band as an int for sorting (high=3 … low=1, unknown=0)."""
    return _LEVELS_PRIORITY.get(atom.get("priority"), 0)


def sort_atoms_by_priority(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort atoms high→medium→low priority, stable within each band.

    The bank's `priority` field drives the F-shaped reading order within a
    matched group (design notes: "matched first, then by priority within
    matched"). Everything in this list is already matched, so priority is the
    only remaining ordering signal.
    """
    return sorted(atoms, key=priority_key, reverse=True)


def match_skills(
    jd_skills: list[str],
    cv_skill_index: dict[str, dict[str, Any]],
    *,
    threshold: float = 0.8,
) -> list[SkillMatch]:
    """Match JD skill requirements against the CV skill index.

    For each JD skill, tries:
    1. Exact match in the CV index.
    2. Substring / containment match against CV index keys (skipped for
       short queries — 1-2 char tokens false-match on intraword substrings).
    3. Fuzzy match (``fuzz.ratio``) against all CV tokens.

    Returns matches with ``score >= threshold``, sorted best-first.
    """
    results: list[SkillMatch] = []

    for jd_skill in jd_skills:
        query = normalize_skill(jd_skill)
        if not query:
            continue

        best_score = 0.0
        best_match: dict[str, Any] | None = None

        # 1. Exact match.
        if query in cv_skill_index:
            best_score = 1.0
            best_match = cv_skill_index[query]

        # 2. Substring match against index keys.
        if best_score < 1.0 and len(query) >= 3:
            for cv_skill, meta in cv_skill_index.items():
                score = _substring_score(query, cv_skill)
                if score > best_score:
                    best_score = score
                    best_match = meta

        # 3. Fuzzy match.
        if best_score < threshold:
            for cv_skill, meta in cv_skill_index.items():
                score = _fuzzy_score(query, cv_skill)
                if score > best_score:
                    best_score = score
                    best_match = meta

        if best_score >= threshold and best_match is not None:
            results.append(
                SkillMatch(
                    cv_skill=best_match["original"],
                    score=best_score,
                    category=best_match["category"],
                    sub_category=best_match["sub_category"],
                )
            )

    results.sort(key=lambda m: m.score, reverse=True)
    return results
