"""Answer "what should I learn next?" for one job description.

Every term a JD demands lands in exactly one of four tiers, ordered by how
much work it would take to claim the skill:

===========  ==========================================================
covered      On the live CV and interviewable today. Nothing to do.
stale        On the live CV, but unused long enough (or flagged
             `needs_refresh`) that it would need study before an
             interview. Not a gap — a risk: a recruiter is being shown a
             skill that cannot yet be defended.
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
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from services.portfolio.matching.baseline import BaselineError, is_stale
from services.portfolio.matching.matcher import LEVEL_STRENGTH
from services.portfolio.matching.normalize import normalize_jd_text
from services.portfolio.matching.parser import extract_mentions
from services.portfolio.matching.taxonomy import build_skill_index, normalize_skill


Tier = Literal["covered", "stale", "unvouched", "deferred", "unknown"]

# Ordered cheapest-to-close first; also the display order on the report.
TIERS: tuple[Tier, ...] = ("covered", "stale", "unvouched", "deferred", "unknown")


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
        """Share of requirements defensible in an interview today (0.0-1.0).

        Stale skills are excluded deliberately: they are on the CV, but
        counting them would report a readiness the operator does not have.
        """
        if not self.gaps:
            return 1.0
        return len(self.by_tier("covered")) / len(self.gaps)

    @property
    def interview_risks(self) -> tuple[SkillGap, ...]:
        """Skills this JD asks for that the CV claims but cannot yet defend."""
        return self.by_tier("stale")


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

    return parse_vocabulary(raw)


def parse_vocabulary(raw: Any) -> list[dict[str, Any]]:
    """Validate an already-parsed vocabulary payload.

    Split from :func:`load_vocabulary` so a vocabulary read from Postgres
    validates through exactly the same rules as one read from disk.
    """
    terms = raw.get("terms") if isinstance(raw, dict) else None
    if not isinstance(terms, list) or not terms:
        raise BaselineError("JD vocabulary must have a non-empty 'terms' list")

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
        if normalize_skill(atom["atom"]) not in live_index:
            tier = "unvouched"
        else:
            # On the CV — but claiming it and defending it are different
            # things. A skill unused for years is shown to a recruiter while
            # needing nearly as much study as one never learned.
            tier = "stale" if is_stale(atom) else "covered"
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


# Capitalised or all-caps tokens (proper nouns, acronyms), 2+ chars, hyphens
# allowed (CI/CD, single-page apps). Deliberately loose — noise is the point;
# a human skims frequency-sorted output, this never feeds an index unattended.
_TECHNICAL_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9+#.-]{1,}\b")

# Common capitalised JD filler that would otherwise dominate the frequency
# count. Not exhaustive by design: whatever leaks through is exactly the
# noise a human filters while skimming, not a correctness bug to chase.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "you",
        "our",
        "team",
        "role",
        "years",
        "experience",
        "strong",
        "ability",
        "work",
        "working",
        "join",
        "company",
        "we",
        "will",
        "must",
        "have",
        "is",
        "are",
        "to",
        "of",
        "in",
        "a",
        "an",
        "as",
        "including",
        "such",
        "etc",
        "environment",
        "skills",
        "knowledge",
        "understanding",
        "required",
        "preferred",
        "responsibilities",
        "requirements",
        "about",
        "who",
        "what",
    }
)


def report_unrecognized(
    jd_text: str, vocabulary: list[dict[str, Any]], *, top_n: int = 20
) -> list[tuple[str, int]]:
    """Technical-looking tokens the vocabulary doesn't know, by frequency.

    A suggestion feed for a human growing :data:`data/jd_vocabulary.json` —
    never an automatic vocabulary source, since it is deliberately noisy.
    Doubles as the coverage metric: once real JDs come back mostly stopword
    noise, the vocabulary is complete enough to stop hand-curating.
    """
    known = {normalize_skill(entry["atom"]) for entry in vocabulary}
    known.update(
        normalize_skill(alias)
        for entry in vocabulary
        for alias in entry.get("aliases", [])
    )

    normalized = normalize_jd_text(jd_text)
    counts: Counter[str] = Counter()
    for match in _TECHNICAL_TOKEN_RE.finditer(normalized):
        token = match.group(0)
        key = normalize_skill(token)
        if not key or key in known or token.lower() in _STOPWORDS:
            continue
        counts[token] += 1

    return counts.most_common(top_n)
