"""Tests for app.matching.parser."""

from app.matching.parser import extract_skills_from_jd
from app.matching.taxonomy import build_skill_index


SAMPLE_SKILLS = [
    {
        "name": "Backend",
        "sub_categories": [
            {"name": "languages", "items": ["Python 3.14+"]},
            {"name": "frameworks", "items": ["FastAPI", "Django", "DRF"]},
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


class TestExtractSkillsFromJd:
    def test_exact_skill_in_text(self):
        jd = "We need a Python developer with FastAPI experience."
        skills = extract_skills_from_jd(jd, INDEX)
        assert "python" in skills
        assert "fastapi" in skills

    def test_comma_separated_list(self):
        jd = "Required: Python, FastAPI, PostgreSQL, Redis"
        skills = extract_skills_from_jd(jd, INDEX)
        assert "python" in skills
        assert "fastapi" in skills
        assert "postgres" in skills
        assert "redis" in skills

    def test_alias_resolved(self):
        jd = "Experience with K8s and DRF required."
        skills = extract_skills_from_jd(jd, INDEX)
        # DRF is in the index as alias for django rest framework
        assert any("django" in s or "drf" in s for s in skills)

    def test_empty_jd(self):
        assert extract_skills_from_jd("", INDEX) == []

    def test_empty_index(self):
        assert extract_skills_from_jd("Python FastAPI", {}) == []

    def test_no_skills_found(self):
        jd = "Looking for a marketing manager with communication skills."
        skills = extract_skills_from_jd(jd, INDEX)
        assert len(skills) == 0

    def test_deduplicates(self):
        jd = "Python, Python, python"
        skills = extract_skills_from_jd(jd, INDEX)
        assert skills.count("python") == 1

    def test_bare_token_does_not_leak_into_compound_key(self):
        # Bank-style index: compound alias keys are standalone entries. A
        # bare "GCP" comma item is a whole token inside "gcp bigquery", so
        # it must attribute "gcp" only, never the BigQuery/AR compound keys.
        index = {
            "gcp": {"category": "Cloud platforms", "sub_category": "tools"},
            "gcp bigquery": {"category": "Cloud platforms", "sub_category": "tools"},
            "gcp artifact registry": {
                "category": "Cloud platforms",
                "sub_category": "tools",
            },
        }
        skills = extract_skills_from_jd("Cloud: AWS, GCP, Azure", index)
        assert "gcp" in skills
        assert "gcp bigquery" not in skills
        assert "gcp artifact registry" not in skills

    def test_forward_match_requires_token_boundary(self):
        # "git" inside the compound item "GitHub Actions" is mid-word; a
        # standalone "git" item still matches.
        index = {
            "git": {"category": "Backend", "sub_category": "tools"},
            "github": {"category": "Backend", "sub_category": "tools"},
        }
        assert "git" not in extract_skills_from_jd("Uses GitHub Actions daily", index)
        assert "git" in extract_skills_from_jd("git rebase, GitHub", index)
