"""Skill taxonomy: alias map, normalization, and CV skill index."""

from __future__ import annotations

import re
from typing import Any


# Canonical name → set of aliases (all lowercase).
_ALIASES: dict[str, set[str]] = {
    "kubernetes": {"k8s"},
    "javascript": {"js"},
    "typescript": {"ts"},
    "postgres": {"postgresql", "psql"},
    "django rest framework": {"drf"},
    "amazon web services": {"aws"},
    "google cloud platform": {"gcp"},
    "microsoft azure": {"azure"},
    "continuous integration": {"ci"},
    "continuous deployment": {"cd"},
    "ci/cd": {"ci cd", "ci-cd"},
    "rest api": {"rest apis"},
    "graphql": {"gql"},
    "docker": {"docker"},
    "redis": {"redis"},
    "celery": {"celery"},
    "sqlalchemy": {"sa"},
    "pytest": {"py.test"},
    "github actions": {"gh actions"},
    "gitlab ci": {"gitlab ci/cd"},
}

# Build reverse map: alias (lowercase) → canonical name (lowercase).
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in _ALIASES.items():
    _ALIAS_TO_CANONICAL[canonical] = canonical
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias] = canonical

_VERSION_RE = re.compile(r"[\s]*[\d]+(?:\.[\d]+)*[\+]*$")
_STRIP_RE = re.compile(r"[:;()–—\-/]+$")

# Tool names whose trailing digit is part of the name, not a version suffix.
# Without the guard "D2" → "d" and "S3" → "s" after version-stripping, which
# silently breaks matching for these (and any future) such atoms.
_NO_VERSION_STRIP = frozenset({"d2", "s3"})

# Curated US/UK spelling variants seen in CV/JD copy. Generic suffix rules
# are deliberately avoided ("advertise" is not "advertize"); only real pairs
# are listed. normalize_skill maps either spelling to the US canonical form,
# so "query optimisation" and "query optimization" resolve identically.
_UK_TO_US: dict[str, str] = {
    "analyse": "analyze",
    "analysed": "analyzed",
    "authorise": "authorize",
    "authorised": "authorized",
    "authorisation": "authorization",
    "behaviour": "behavior",
    "behavioural": "behavioral",
    "cancelled": "canceled",
    "cancelling": "canceling",
    "centre": "center",
    "colour": "color",
    "customise": "customize",
    "customised": "customized",
    "defence": "defense",
    "licence": "license",
    "modelling": "modeling",
    "normalise": "normalize",
    "normalised": "normalized",
    "normalisation": "normalization",
    "optimise": "optimize",
    "optimised": "optimized",
    "optimising": "optimizing",
    "optimisation": "optimization",
    "organise": "organize",
    "organisation": "organization",
    "recognise": "recognize",
    "serialise": "serialize",
    "serialisation": "serialization",
    "synchronise": "synchronize",
    "synchronisation": "synchronization",
    "utilise": "utilize",
    "utilised": "utilized",
    "visualise": "visualize",
    "visualisation": "visualization",
}

# Single scan replacing any UK word inside a (possibly compound) skill name.
_US_SUB = re.compile(r"\b(?:" + "|".join(re.escape(uk) for uk in _UK_TO_US) + r")\b")


def _us_lookup(match: re.Match[str]) -> str:
    return _UK_TO_US[match.group(0)]


def normalize_skill(name: str) -> str:
    """Normalize a skill name for comparison.

    Strips version suffixes, trailing punctuation, and lowercases.
    Resolves US/UK spelling variants to the US form, then aliases to
    canonical names. The suffix restrips repeat until stable, so
    normalization is idempotent (a fixpoint).

    ``"Python 3.14+"`` → ``"python"``
    ``"Grafana)"`` → ``"grafana"``
    ``"K8s"`` → ``"kubernetes"``
    ``"FastAPI"`` → ``"fastapi"``
    ``"query optimisation"`` → ``"query optimization"``
    ``"D2"`` → ``"d2"`` (trailing digit kept for tool names)
    """
    s = name.strip().lower()
    while True:
        prev = s
        if s not in _NO_VERSION_STRIP:
            s = _VERSION_RE.sub("", s)
        s = _STRIP_RE.sub("", s)
        s = s.strip()
        if s == prev:
            break
    s = _US_SUB.sub(_us_lookup, s)
    return _ALIAS_TO_CANONICAL.get(s, s)


def extract_skill_tokens(skill_str: str) -> list[str]:
    """Split a compound skill string into individual normalized tokens.

    ``"PostgreSQL: schema design, migrations"`` → ``["postgres", "schema design", "migrations"]``
    ``"FastAPI/Django"`` → ``["fastapi", "django"]``
    ``"Python"`` → ``["python"]``
    """
    parts = re.split(r"[:;/,|]", skill_str)
    tokens = []
    for part in parts:
        t = normalize_skill(part)
        if t:
            tokens.append(t)
    return tokens


def build_skill_index(
    skills: list[dict[str, Any]],
    additional_skills: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a lookup index from CV skill data.

    Returns a dict mapping normalized skill name to its metadata.
    Both the direct normalization and alias targets are indexed, so a
    JD skill like "DRF" (alias → "django rest framework") is found even
    if the CV stores the abbreviation "DRF" as a standalone item.

    ``{"python": {"category": "Backend", "sub_category": "languages", "original": "Python 3.14+"}}``

    Compound skill strings are split so individual tokens are also indexable.
    """
    index: dict[str, dict[str, Any]] = {}

    def _index_skills(skill_list: list[dict[str, Any]]) -> None:
        for cat in skill_list:
            cat_name = cat.get("name", "")
            for sub in cat.get("sub_categories", []):
                sub_name = sub.get("name", "")
                for item in sub.get("items", []):
                    meta = {
                        "category": cat_name,
                        "sub_category": sub_name,
                        "original": item,
                    }
                    # Index raw lowercased item (e.g. "DRF" → "drf").
                    # Empty items are skipped — a "" index key would match
                    # every query via substring containment.
                    raw_key = item.strip().lower()
                    if raw_key and raw_key not in index:
                        index[raw_key] = meta
                    # Index individual tokens from compound skills.
                    for token in extract_skill_tokens(item):
                        if token not in index:
                            index[token] = meta
                    # Index under alias targets for bidirectional lookup.
                    direct = normalize_skill(item)
                    if direct and direct not in index:
                        index[direct] = meta

    _index_skills(skills)
    if additional_skills:
        _index_skills(additional_skills)
    return index
