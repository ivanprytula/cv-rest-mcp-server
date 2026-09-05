"""Generate a tailored CV dict from a job description and the skill bank.

The skill bank (``data/cv_baseline.json``) is the matching source; the live
CV is only read to enforce the trust policy (a matched atom must already be
vouched for on the public CV) and to pass non-skill sections through.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz

from services.portfolio.matching.baseline import build_atom_index
from services.portfolio.matching.matcher import LEVEL_STRENGTH, priority_key
from services.portfolio.matching.parser import extract_mentions
from services.portfolio.matching.taxonomy import build_skill_index, normalize_skill


logger = logging.getLogger(__name__)

_HINT_SPLIT = " > "
_ADDITIONAL_GROUP = "Additional skills"

# Sort sentinel larger than any real canonical position: unknown groups,
# sub_categories, or items land after every known one, stable by encounter.
_UNKNOWN_POS = 1 << 30

# Fuzzy fallback caps: typo'd JD words are matched against the bank index, but
# a JD can be megabytes — bound the work so a huge upload stays cheap.
_FUZZY_MAX_TOKENS = 300


def company_slug(name: str) -> str:
    """Turn a company name into a filesystem-safe slug.

    ``"EPC Network"`` → ``"epc_network"``
    ``"Netflix"`` → ``"netflix"``
    """
    slug = unicodedata.normalize("NFKD", name)
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def extract_company(jd_text: str) -> str:
    """Best-effort extraction of the company name from a JD.

    Looks for common patterns: "at Acme Corp", "Company: Acme",
    "Acme is hiring", etc.  Returns empty string if nothing confidence-
    inspiring is found.
    """
    if not jd_text:
        return ""

    # Pattern: "at <Company>" after "work at" / "join" / line start.
    # Match 1-3 title-case words (company names are usually short).
    m = re.search(
        r"(?:^|\bwork at\b|\bjoin\b|\bat\b)\s+"
        r"(?:the\s+|a\s+|an\s+)?"
        r"([A-Z][A-Za-z0-9.&]{2,40}"
        r"(?:\s+[A-Z][A-Za-z0-9.&]{2,40}){0,2})",
        jd_text,
    )
    if m:
        return m.group(1).strip()

    # Pattern: "Company: <Name>" or "Company name: <Name>".
    m = re.search(r"(?:Company|Employer)\s*[:]\s*(.+)", jd_text, re.IGNORECASE)
    if m:
        raw = re.split(r"[\n\r]", m.group(1))[0].strip()
        return raw[:60]

    return ""


def _fuzzy_candidates(
    jd_text: str, atom_index: dict[str, dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """Typo/paraphrase fallback: fuzzy-match unclaimed JD words to atoms.

    The qualifier pass only surfaces skills that hit the index exactly or as
    a substring. Words the JD uses but the index does not contain (misspelled
    or paraphrased skill names, e.g. "pyton" → Python) get a fuzzy check
    (``fuzz.ratio`` / ``partial_ratio`` ≥ *threshold*). Such matches carry no
    qualifier, so they impose no level constraint.
    """
    words = re.findall(r"[a-z][a-z0-9+#.]{2,30}", jd_text.lower())
    unclaimed: list[str] = []
    for word in words:
        # The word regex includes ".", so "Redis." surfaces as "redis." and
        # misses the index — strip cosmetic punctuation or the fuzzy pass
        # would silently re-add an already-mentioned, level-filtered atom.
        # Membership is checked on the normalized key too, so the JD's
        # "postgresql" spelling cannot bypass a level-vetted "postgres" atom.
        key = word.rstrip(".,")
        if key in atom_index or normalize_skill(key) in atom_index or key in unclaimed:
            continue
        unclaimed.append(key)
    unclaimed = unclaimed[:_FUZZY_MAX_TOKENS]

    candidates: dict[str, dict[str, Any]] = {}
    for word in unclaimed:
        best_score = 0.0
        best_atom: dict[str, Any] | None = None
        for key, atom in atom_index.items():
            score = max(
                fuzz.partial_ratio(word, key) / 100.0, fuzz.ratio(word, key) / 100.0
            )
            if score > best_score:
                best_score = score
                best_atom = atom
        if best_score >= threshold and best_atom is not None:
            canonical = normalize_skill(best_atom["atom"])
            candidates.setdefault(canonical, best_atom)
    return list(candidates.values())


def _qualifies(atom: dict[str, Any], required_level: str | None) -> bool:
    """True when the atom's level meets the JD-required level (None = no constraint)."""
    if required_level is None:
        return True
    return LEVEL_STRENGTH.get(atom.get("level"), 0) >= LEVEL_STRENGTH[required_level]


def _trust_filter(
    atoms: list[dict[str, Any]], live_cv_index: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split matched atoms into those vouched for on the live CV and the rest.

    The trust policy: only atoms whose canonical form is a key in the live CV
    index may appear in tailored output — a bank skill the operator never put
    on the public CV must not reach a recruiter. Dropped atoms are logged as a
    warning so the operator sees what the JD asked for but couldn't show.
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for atom in atoms:
        if normalize_skill(atom["atom"]) in live_cv_index:
            kept.append(atom)
        else:
            dropped.append(atom)
    if dropped:
        logger.warning(
            "Trust policy dropped %d matched atom(s) not on the live CV: %s",
            len(dropped),
            ", ".join(sorted(d["atom"] for d in dropped)),
        )
    return kept, dropped


def _canonical_skill_order(live_cv: dict[str, Any]) -> dict[str, Any]:
    """Map the live CV's skills structure to stable ordering positions.

    The operator's public CV is the ordering template for tailored output:
    top-level groups, sub_categories, and items follow the same sequence a
    recruiter sees on the real CV. That keeps a tailored revision readable
    next to the live one — e.g. "Backend development > languages" (Python)
    always precedes "frameworks", and the cloud block sorts after testing
    regardless of JD mention order. Atoms without a canonical slot (e.g. the
    "Additional skills" bucket, currently empty on the live CV) fall back to
    bank-priority order.
    """
    order: dict[str, Any] = {}
    for group_index, group in enumerate(live_cv.get("skills", [])):
        subs: dict[str, Any] = {}
        for sub_index, sub in enumerate(group.get("sub_categories", [])):
            subs[sub.get("name", "")] = {
                "index": sub_index,
                "items": {
                    normalize_skill(item): item_index
                    for item_index, item in enumerate(sub.get("items", []))
                },
            }
        order[group.get("name", "")] = {"index": group_index, "subs": subs}
    return order


def _group_atoms(
    atoms: list[dict[str, Any]], canonical: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group matched atoms into CV skills/additional_skills structures.

    ``category_hint`` ("Backend development > frameworks") maps group → top-level
    category and sub → sub_category. Hints under "Additional skills" land in
    ``additional_skills``. Groups, sub_categories and items are ordered by the
    live CV's canonical structure (see ``_canonical_skill_order``); anything
    without a canonical slot keeps priority order (high → low), stable within
    each band.
    """
    buckets = {"skills": {}, "additional": {}}
    for seq, atom in enumerate(atoms):
        group, _, sub = atom["category_hint"].partition(_HINT_SPLIT)
        section = "additional" if group == _ADDITIONAL_GROUP else "skills"
        bucket = buckets[section].setdefault(
            group, {"name": group, "sub_categories": {}}
        )
        sub_bucket = bucket["sub_categories"].setdefault(
            sub, {"name": sub, "atoms": []}
        )
        sub_bucket["atoms"].append((atom, seq))

    def _group_pos(name: str) -> int:
        return canonical.get(name, {}).get("index", _UNKNOWN_POS)

    def _sub_pos(group: str, sub: str) -> int:
        return (
            canonical.get(group, {})
            .get("subs", {})
            .get(sub, {})
            .get("index", _UNKNOWN_POS)
        )

    def _item_pos(atom: dict[str, Any], group: str, sub: str) -> int:
        return (
            canonical.get(group, {})
            .get("subs", {})
            .get(sub, {})
            .get("items", {})
            .get(normalize_skill(atom["atom"]), _UNKNOWN_POS)
        )

    def _item_key(pair: tuple[dict[str, Any], int], group: str, sub: str) -> tuple:
        atom, seq = pair
        return (_item_pos(atom, group, sub), -priority_key(atom), seq)

    skills: list[dict[str, Any]] = []
    additional: list[dict[str, Any]] = []
    for section, out in (("skills", skills), ("additional", additional)):
        groups = sorted(buckets[section].values(), key=lambda g: _group_pos(g["name"]))
        for group in groups:
            sub_categories = sorted(
                group["sub_categories"].values(),
                key=lambda s: _sub_pos(group["name"], s["name"]),
            )
            out.append(
                {
                    "name": group["name"],
                    "sub_categories": [
                        {
                            "name": sub["name"],
                            "items": [
                                atom["atom"]
                                for atom, _ in sorted(
                                    sub["atoms"],
                                    key=lambda p: _item_key(
                                        p, group["name"], sub["name"]
                                    ),
                                )
                            ],
                        }
                        for sub in sub_categories
                    ],
                }
            )
    return skills, additional


def tailor_cv(
    jd_text: str,
    baseline_atoms: list[dict[str, Any]],
    live_cv: dict[str, Any],
    *,
    title: str = "",
    threshold: float = 0.8,
) -> dict[str, Any]:
    """Build a tailored copy of *live_cv* from *jd_text* + the skill bank.

    Thin wrapper over :func:`tailor_with_gaps` keeping the tailored document
    as the sole return value — the shape ``routes.py`` and the ``match_jd``
    MCP tool consume.
    """
    tailored, _ = tailor_with_gaps(
        jd_text, baseline_atoms, live_cv, title=title, threshold=threshold
    )
    return tailored


def tailor_with_gaps(
    jd_text: str,
    baseline_atoms: list[dict[str, Any]],
    live_cv: dict[str, Any],
    *,
    title: str = "",
    threshold: float = 0.8,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Tailor *live_cv*, also returning the atoms the trust policy dropped.

    The dropped atoms are bank skills a JD asked for that the live CV does not
    vouch for — the "unvouched" gap tier. ``tailor_cv`` discards them; gap
    analysis needs them.

    Steps:
    1. Build an attribution map: every JD mention (qualifier-aware) picks a
       bank atom, carrying its required level.
    2. Reject atoms whose bank level is below the JD-required level; add
       typo/paraphrase fuzzy hits with no level constraint.
    3. Enforce the trust policy: drop atoms not vouched for on the live CV.
    4. Rebuild the ``skills``/``additional_skills`` sections from the
       survivors, grouped by ``category_hint``. Groups, sub_categories and
       items follow the live CV's canonical ordering (so "Python" always
       heads "Backend development"); unmatched slots keep bank-priority order.
    5. Pass every other section through unchanged (``experience``,
       ``summary``, ``education``, ``languages``, …) and override ``title``
       when provided.

    A JD that matches nothing yields empty skill sections — the tailored
    result is a faithful match verdict, not a padded copy of the live CV.
    """
    atom_index = build_atom_index(baseline_atoms)

    # Required level per atom canonical (strongest mention wins).
    required: dict[str, str | None] = {}
    for mention in extract_mentions(jd_text, atom_index):
        atom = atom_index[mention.skill]
        canonical = normalize_skill(atom["atom"])
        if canonical not in required:
            required[canonical] = mention.level
        elif mention.level is not None:
            prev = required[canonical]
            if prev is None or LEVEL_STRENGTH[mention.level] > LEVEL_STRENGTH[prev]:
                required[canonical] = mention.level

    candidates: dict[str, dict[str, Any]] = {}
    for canonical, need in required.items():
        atom = atom_index[canonical] if canonical in atom_index else None
        # Required keys come from atom canonical, which is guaranteed indexed.
        if atom is None:
            continue
        if _qualifies(atom, need):
            candidates.setdefault(canonical, atom)

    # Fuzzy fallback: unclaimed JD words impose no level constraint.
    for atom in _fuzzy_candidates(jd_text, atom_index, threshold):
        candidates.setdefault(normalize_skill(atom["atom"]), atom)

    live_index = build_skill_index(
        live_cv.get("skills", []), live_cv.get("additional_skills")
    )
    trusted, dropped = _trust_filter(list(candidates.values()), live_index)

    skills, additional = _group_atoms(trusted, _canonical_skill_order(live_cv))

    tailored = dict(live_cv)
    tailored["skills"] = skills
    tailored["additional_skills"] = additional
    if title:
        tailored["title"] = title
    return tailored, dropped
