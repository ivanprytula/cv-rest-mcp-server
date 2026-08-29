"""Tests for qualifier-aware mention extraction (app.matching.parser)."""

from app.matching.parser import extract_mentions, extract_skills_from_jd
from app.matching.taxonomy import build_skill_index, normalize_skill


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


def levels(mentions):
    """Map normalized skill -> strongest level, hiding key-variant noise (postgres vs postgresql)."""
    merged: dict[str, str | None] = {}
    strength = {None: 0, "basic": 1, "middle": 2, "expert": 3}
    for m in mentions:
        key = normalize_skill(m.skill)
        if strength.get(m.level, 0) >= strength.get(merged.get(key), 0):
            merged[key] = m.level
    return merged


class TestExtractMentions:
    def test_unqualified_mention_has_none_level(self):
        mentions = extract_mentions("Required: Python, FastAPI, PostgreSQL", INDEX)
        by = levels(mentions)
        assert by["python"] is None
        assert by["fastapi"] is None
        assert by["postgres"] is None

    def test_solid_experience_is_expert(self):
        mentions = extract_mentions("We need solid experience with Python.", INDEX)
        assert levels(mentions)["python"] == "expert"

    def test_deep_knowledge_is_expert(self):
        mentions = extract_mentions("Deep knowledge of PostgreSQL.", INDEX)
        assert levels(mentions)["postgres"] == "expert"

    def test_strong_knowledge_is_expert(self):
        mentions = extract_mentions("Strong knowledge of Django required.", INDEX)
        assert levels(mentions)["django"] == "expert"

    def test_bare_experience_is_middle(self):
        mentions = extract_mentions("Experience with FastAPI and Redis.", INDEX)
        by = levels(mentions)
        assert by["fastapi"] == "middle"
        assert by["redis"] == "middle"

    def test_expert_in_is_expert(self):
        mentions = extract_mentions("Looking for an expert in PostgreSQL.", INDEX)
        assert levels(mentions)["postgres"] == "expert"

    def test_familiarity_is_basic(self):
        mentions = extract_mentions("Familiarity with Redis and PostgreSQL.", INDEX)
        by = levels(mentions)
        assert by["redis"] == "basic"
        assert by["postgres"] == "basic"

    def test_some_experience_is_basic(self):
        mentions = extract_mentions("Some experience with Django is enough.", INDEX)
        assert levels(mentions)["django"] == "basic"

    def test_five_plus_years_is_expert(self):
        mentions = extract_mentions("5+ years of PostgreSQL development.", INDEX)
        assert levels(mentions)["postgres"] == "expert"

    def test_two_years_is_middle(self):
        mentions = extract_mentions("2 years of experience with FastAPI.", INDEX)
        assert levels(mentions)["fastapi"] == "middle"

    def test_one_year_is_basic(self):
        mentions = extract_mentions("1 year with FastAPI on the side.", INDEX)
        assert levels(mentions)["fastapi"] == "basic"

    def test_months_is_basic(self):
        mentions = extract_mentions("6 months of Python.", INDEX)
        assert levels(mentions)["python"] == "basic"

    def test_multi_word_skill_in_qualifier(self):
        mentions = extract_mentions(
            "Solid experience with Django REST Framework.", INDEX
        )
        by = levels(mentions)
        assert by["django rest framework"] == "expert"

    def test_skill_not_in_cv_is_not_emitted(self):
        mentions = extract_mentions(
            "Solid experience with Rust and Go.", INDEX
        )  # Rust/Go absent from the CV index
        assert mentions == []

    def test_strongest_level_wins_on_dedup(self):
        mentions = extract_mentions(
            "Familiarity with Python but solid experience with Python.", INDEX
        )
        assert levels(mentions)["python"] == "expert"

    def test_years_outrank_phrase_on_overlap(self):
        mentions = extract_mentions(
            "5+ years of experience with Python and familiarity with Redis.", INDEX
        )
        by = levels(mentions)
        assert by["python"] == "expert"  # years (expert) beats bare-experience (middle)
        assert by["redis"] == "basic"

    def test_empty_jd(self):
        assert extract_mentions("", INDEX) == []

    def test_empty_index(self):
        assert extract_mentions("Solid experience with Python", {}) == []

    def test_raw_captures_qualifier_phrase(self):
        mentions = extract_mentions("Solid experience with Python.", INDEX)
        assert mentions[0].raw.lower() == "solid experience with python"
        assert "solid" in mentions[0].raw.lower()

    def test_extract_skills_from_jd_still_finds_all(self):
        jd = "Solid experience with Python and FastAPI. Familiarity with Redis."
        skills = extract_skills_from_jd(jd, INDEX)
        assert "python" in skills
        assert "fastapi" in skills
        assert "redis" in skills


class TestUkUsSpellings:
    def _index(self, item):
        return build_skill_index(
            [
                {
                    "name": "Backend",
                    "sub_categories": [{"name": "practices", "items": [item]}],
                }
            ]
        )

    def test_us_cv_skill_matches_uk_spelling_in_jd(self):
        index = self._index("Query optimization")
        mentions = extract_mentions("Solid experience with query optimisation.", index)
        assert any(
            m.skill == "query optimization" and m.level == "expert" for m in mentions
        )

    def test_uk_cv_skill_matches_us_spelling_in_jd(self):
        index = self._index("Query optimisation")
        mentions = extract_mentions("Experience with query optimization.", index)
        assert any(
            m.skill == "query optimization" and m.level == "middle" for m in mentions
        )

    def test_uk_spelling_surfaces_in_plain_skill_scan(self):
        index = self._index("Data visualisation")
        skills = extract_skills_from_jd("Required: data visualization", index)
        assert "data visualization" in skills
