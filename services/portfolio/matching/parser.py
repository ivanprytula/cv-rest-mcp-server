"""Extract skill mentions from job-description text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from services.portfolio.matching.taxonomy import normalize_skill


def _extract_list_items(text: str) -> list[str]:
    """Pull comma/semicolon-separated items from text."""
    items: list[str] = []
    for segment in re.split(r"[;\n]", text):
        for item in re.split(r",", segment):
            item = item.strip().strip("-*•·")
            item = re.sub(r"\s+", " ", item)
            if len(item) >= 2:
                items.append(item)
    return items


# Characters a skill key/token may contain. Used to require token boundaries
# (a preceding/following character outside this set) for item↔key matches.
# Period is NOT included: "fastapi." is a list item ending in sentence
# punctuation, and "postgres" inside "postgresql" is mid-word — both must
# stay visible to the boundary checks.
_KEY_CHARS = "a-z0-9+#"


def _forward_contains(key: str, item_lower: str) -> bool:
    """True when ``key`` appears in a comma item as a whole token.

    ``"python" ⊂ "python 3.14"`` → True; ``"git"`` inside ``"github actions"``
    → False. Without the boundary, a bare "GitHub Actions" item would
    attribute the "Git" skill via mid-word containment.
    """
    return (
        re.search(rf"(?<![{_KEY_CHARS}]){re.escape(key)}(?![{_KEY_CHARS}])", item_lower)
        is not None
    )


def _reverse_contains(item_lower: str, key: str) -> bool:
    """True when a comma item is a partial word inside a token of ``key``.

    ``"postgres" ⊂ "postgresql"`` → True (proper prefix of the key's only
    token). A bare ``"gcp"`` item vs the compound key ``"gcp bigquery"`` →
    False: "gcp" is itself a whole token there, so the item must attribute
    the "gcp" key only, never the "gcp bigquery" alias. Without this, a
    plain "GCP" mention silently leaks BigQuery / Artifact Registry.
    """
    return any(
        item_lower != token and item_lower in token
        for token in re.findall(f"[{_KEY_CHARS}]+", key)
    )


def extract_skills_from_jd(
    jd_text: str, cv_skill_index: dict[str, dict[str, Any]]
) -> list[str]:
    """Extract skill mentions from a job description.

    Uses the CV skill index for fast substring lookups on the full JD text.
    Multi-word CV skills (e.g. "Django REST Framework") are matched as
    complete phrases first, then individual tokens as fallback.

    Returns a deduplicated list of normalized skill names (lowercase).
    """
    if not jd_text or not cv_skill_index:
        return []

    text_lower = jd_text.lower()
    found: list[str] = []

    # Phase 1: match multi-word CV skills as complete phrases (longest first).
    multi_word = sorted([k for k in cv_skill_index if " " in k], key=len, reverse=True)
    for skill in multi_word:
        if skill in text_lower:
            found.append(skill)

    # Phase 2: extract comma-separated list items for shorter skills. Matches
    # are token-boundary-aware in both directions: "python" within a "Python
    # 3.14" item yes; a compound item "GitHub Actions" must not attribute
    # "Git" mid-word; a bare "GCP" item must not surface the "gcp bigquery"
    # compound key (its whole token would otherwise match by containment).
    for item in _extract_list_items(jd_text):
        item_lower = item.lower()
        for cv_skill in cv_skill_index:
            if _forward_contains(cv_skill, item_lower) or _reverse_contains(
                item_lower, cv_skill
            ):
                if cv_skill not in found:
                    found.append(cv_skill)

    # Phase 3: single-word tokens from the full text. The word regex keeps
    # "." (for "3.14") but the token may end in sentence punctuation, which
    # the index keys never carry — strip it before lookup.
    words = {
        word.rstrip(".,;:")
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]{1,30}", text_lower)
    }
    for word in words:
        if word in cv_skill_index and word not in found:
            found.append(word)
        # Also surface the normalized canonical when the word was an exact
        # index key under a different spelling: an item "PostgreSQL" hits the
        # raw key "postgresql" AND the alias-resolved key "postgres". Without
        # this, "PostgreSQL" alone would never report the canonical form.
        norm = normalize_skill(word)
        if norm != word and norm in cv_skill_index and norm not in found:
            found.append(norm)

    return found


# Level vocabulary mirrors the CV skill bank (`data/cv_baseline.json`).
Level = Literal["expert", "middle", "basic"]

_LEVEL_STRENGTH: dict[Level | None, int] = {
    None: 0,
    "basic": 1,
    "middle": 2,
    "expert": 3,
}


@dataclass(frozen=True)
class SkillMention:
    """A skill found in a JD plus the level implied by its qualifier.

    ``level`` is ``None`` when the JD states no qualifier — the matcher
    should treat that as "no constraint". ``raw`` is the JD phrase that
    produced the mention (qualifier head plus surrounding window), useful
    for reviewing why a skill was attributed a level.
    """

    skill: str
    level: Level | None
    raw: str


# How far past a qualifier phrase we look for skill names.
_QUALIFIER_WINDOW = 40

# Qualifier heads, grouped by the level they imply. A skill matched by
# several heads keeps the strongest level (expert > middle > basic).
_EXPERT_HEADS = re.compile(
    r"\b(?:expert-level|expert|mastery|seasoned|proven|strong|solid|deep|"
    r"extensive|advanced|in-depth|comprehensive|exceptional|profound|production)\b"
    r"(?:\s+(?:experience|knowledge|expertise|understanding|background|"
    r"grasp|command|proficiency|track\s+record|skills?))?"
    r"\s+(?:with|in|of|using|at)\s+",
    re.IGNORECASE,
)

_MIDDLE_HEADS = [
    re.compile(
        r"\b(?:experienced|proficient|versed|competent|comfortable)"
        r"\s+(?:in|with|at|using)\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:good|working|hands-on|professional|practical|sound|sufficient)\s+)?"
        r"(?<!some )(?<!basic )"
        r"(?:experience|knowledge|understanding|background)"
        r"\s+(?:with|in|of|using|at)\s+",
        re.IGNORECASE,
    ),
]

_BASIC_HEADS = [
    re.compile(r"\bfamiliar(?:ity)?\s+with\s+", re.IGNORECASE),
    re.compile(
        r"\bbasic\s+(?:knowledge|understanding|experience)\s+(?:with|in|of)\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsome\s+(?:experience|knowledge|exposure)\s+(?:with|in|of|to)\s+",
        re.IGNORECASE,
    ),
    re.compile(r"\bexposure\s+to\s+", re.IGNORECASE),
    re.compile(r"\baware(?:ness)?\s+of\s+", re.IGNORECASE),
    re.compile(
        r"\bentry.level\s+(?:knowledge|experience|understanding)\s+(?:with|in|of)\s+",
        re.IGNORECASE,
    ),
]

_MIDDLE: Level = "middle"
_BASIC: Level = "basic"

_QUALIFIER_HEADS: list[tuple[re.Pattern[str], Level]] = [
    (_EXPERT_HEADS, "expert"),
    *[(p, _MIDDLE) for p in _MIDDLE_HEADS],
    *[(p, _BASIC) for p in _BASIC_HEADS],
]

_YEARS_RE = re.compile(
    r"\b(?P<num>\d+(?:\.\d+)?)\s*\+?\s*(?P<unit>years?|yrs|months?)\b"
    r"(?!\s+ago\b)"
    r"\s+(?:of\s+)?(?:practical\s+|hands-on\s+|professional\s+|relevant\s+)?"
    r"(?:experience\s+)?(?:(?:with|in|using|on)\s+)?",
    re.IGNORECASE,
)

# Also used to end a mention's trailing window at the next qualifier phrase,
# so "5+ years of Python and familiarity with Redis" does not leak "Redis"
# into the years phrase.
_STOP_PATTERNS: list[re.Pattern[str]] = [
    _EXPERT_HEADS,
    *_MIDDLE_HEADS,
    *_BASIC_HEADS,
    _YEARS_RE,
]


def _years_level(num: str, unit: str) -> Level:
    """Map a year/month count to a level: ≥5 years expert, 3–4 middle, else basic."""
    years = float(num)
    if unit.startswith("m"):
        years /= 12.0
    if years >= 5.0:
        return "expert"
    if years >= 3.0:
        return "middle"
    return "basic"


def _skills_in_chunk(
    chunk: str, cv_skill_index: dict[str, dict[str, Any]]
) -> list[str]:
    """Collect CV skills named inside a qualifier's trailing chunk.

    Multi-word skills are matched as complete phrases first, then the
    remaining single-word keys are picked from the tokens. Only keys
    present in the CV index are returned.
    """
    chunk = re.sub(r"[\s.,;]+$", "", chunk.strip())
    if not chunk:
        return []

    # UK/―US normalize the whole chunk first, so "query optimisation"
    # resolves to the "query optimization" canonical CV key either way.
    text = normalize_skill(chunk)
    found: list[str] = []

    # Compound CV items ("REST APIs: OpenAPI contracts, …") are indexed as
    # whole multi-word keys too; they must not be treated as skill phrases,
    # or they hijack the whole window and hide the real skills inside it.
    phrase_keys = (
        k for k in cv_skill_index if " " in k and not re.search(r"[,.:–—]", k)
    )
    for key in sorted(phrase_keys, key=len, reverse=True):
        if key in text:
            found.append(key)

    covered = {word for key in found for word in key.split()}
    for word in sorted(set(re.findall(r"[a-z][a-z0-9+#.]{1,30}", text))):
        if word in covered:
            continue
        if word in cv_skill_index:
            if word not in found:
                found.append(word)
        else:
            norm = normalize_skill(word)
            if norm in cv_skill_index and norm not in found:
                found.append(norm)

    return found


def extract_mentions(
    jd_text: str, cv_skill_index: dict[str, dict[str, Any]]
) -> list[SkillMention]:
    """Extract skill mentions from a JD together with their qualifier level.

    Complements :func:`extract_skills_from_jd` with qualifier awareness:

    1. Qualifier phrases (``"Solid experience with X"``, ``"Familiarity with X"``,
       ``"5+ years of X"``) attribute a level — ``expert`` / ``middle`` / ``basic``.
    2. Skills mentioned without any qualifier still appear with ``level=None``
       ("no constraint"), so the mention list is complete.

    A skill found under several phrases keeps the strongest level. ``skill``
    is the CV index key (the same string :func:`extract_skills_from_jd` returns).
    """
    if not jd_text or not cv_skill_index:
        return []

    mentions: dict[str, tuple[int, Level | None, str]] = {}

    def _note(skill: str, level: Level | None, raw: str) -> None:
        strength = _LEVEL_STRENGTH.get(level, 0)
        current = mentions.get(skill)
        if current is None or strength > current[0]:
            mentions[skill] = (strength, level, raw)

    def _phrase_window(end: int) -> str:
        raw_win = jd_text[end : end + _QUALIFIER_WINDOW]
        raw_win = re.split(r"[.;\n]", raw_win, maxsplit=1)[0]
        cut = len(raw_win)
        for pattern in _STOP_PATTERNS:
            stop = pattern.search(raw_win)
            if stop and stop.start() < cut:
                cut = stop.start()
        return raw_win[:cut]

    # Phase A — qualifier phrases and year counts.
    for pattern, level in _QUALIFIER_HEADS:
        for match in pattern.finditer(jd_text):
            window = _phrase_window(match.end())
            for skill in _skills_in_chunk(window, cv_skill_index):
                raw = f"{match.group(0).strip()} {window.strip()}".strip()
                _note(skill, level, raw)

    for match in _YEARS_RE.finditer(jd_text):
        level = _years_level(match.group("num"), match.group("unit"))
        window = _phrase_window(match.end())
        for skill in _skills_in_chunk(window, cv_skill_index):
            raw = f"{match.group(0).strip()} {window.strip()}".strip()
            _note(skill, level, raw)

    # Phase B — unqualified mentions keep level=None, unless an equivalent
    # normalized form already carries a level (e.g. "postgres" vs "postgresql").
    attributed_norm = {normalize_skill(skill) for skill in mentions}
    for skill in extract_skills_from_jd(jd_text, cv_skill_index):
        if normalize_skill(skill) not in attributed_norm:
            _note(skill, None, skill)

    return [
        SkillMention(skill=skill, level=level, raw=raw)
        for skill, (_, level, raw) in sorted(mentions.items())
    ]
