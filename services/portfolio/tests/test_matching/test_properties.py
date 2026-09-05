"""Property-based tests for the matching pipeline (Hypothesis).

These complement the example-driven tests. Example tests assert what the
*right* answer is; properties pin invariants that must hold for arbitrary
input — robustness (no crashes), well-formed output, determinism, and
normalization fixpoints. All inputs are generated, so the suite stays
independent of `data/cv.json` content.
"""

import hypothesis.strategies as st
from hypothesis import given

from services.portfolio.matching.parser import extract_mentions
from services.portfolio.matching.taxonomy import (
    _UK_TO_US,
    build_skill_index,
    normalize_skill,
)


SAMPLE_SKILLS = [
    {
        "name": "Backend",
        "sub_categories": [
            {"name": "languages", "items": ["Python 3.14+"]},
            {
                "name": "frameworks",
                "items": ["FastAPI", "Django", "Django REST Framework"],
            },
        ],
    },
    {
        "name": "Databases",
        "sub_categories": [
            {"name": "datastores", "items": ["PostgreSQL", "Redis"]},
        ],
    },
]

INDEX = build_skill_index(SAMPLE_SKILLS)

_VALID_LEVELS = (None, "expert", "middle", "basic")

_JD = st.text(min_size=0, max_size=500)
_SKILL_WORDS = st.sampled_from(
    [
        "python",
        "fastapi",
        "django",
        "redis",
        "postgresql",
        "drf",
        "django rest framework",
        "pyton",
        "kubernetes",
        "java",
        "k8s",
    ]
)


class TestNormalizeSkill:
    @given(s=_JD)
    def test_is_a_fixpoint(self, s):
        once = normalize_skill(s)
        assert normalize_skill(once) == once

    @given(pair=st.sampled_from(sorted(_UK_TO_US.items())))
    def test_uk_us_spellings_canonicalize_together(self, pair):
        uk, us = pair
        assert normalize_skill(uk) == normalize_skill(us)

    @given(uk_word=st.sampled_from(list(_UK_TO_US)))
    def test_uk_spelling_routes_to_us_canonical(self, uk_word):
        assert normalize_skill(uk_word) == _UK_TO_US[uk_word]


class TestExtractMentions:
    @given(jd=_JD)
    def test_output_is_wellformed_stable_and_deduped(self, jd):
        first = extract_mentions(jd, INDEX)
        assert first == extract_mentions(jd, INDEX)

        skills = [m.skill for m in first]
        assert len(skills) == len(set(skills))

        for m in first:
            assert m.skill in INDEX
            assert m.level in _VALID_LEVELS
            assert m.raw
