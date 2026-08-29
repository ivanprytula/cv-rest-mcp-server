"""Tests for app.matching.taxonomy."""

from app.matching.taxonomy import (
    _UK_TO_US,
    build_skill_index,
    extract_skill_tokens,
    normalize_skill,
)


class TestNormalizeSkill:
    def test_lowercases(self):
        assert normalize_skill("Python") == "python"

    def test_strips_version(self):
        assert normalize_skill("Python 3.14+") == "python"

    def test_strips_trailing_punctuation(self):
        assert normalize_skill("PostgreSQL:") == "postgres"

    def test_strips_trailing_parentheses(self):
        # Compound items like "…, Prometheus, Grafana)" leave dangling ")"
        # tokens after comma-splitting; they must normalize to the bare skill.
        assert normalize_skill("Grafana)") == "grafana"
        assert normalize_skill("ty)") == "ty"
        assert normalize_skill("Redis (NoSQL: caching") == "redis (nosql: caching"

    def test_tool_names_keep_trailing_digits(self):
        # "D2" and "S3" are tool names, not version suffixes.
        assert normalize_skill("D2") == "d2"
        assert normalize_skill("S3") == "s3"
        assert normalize_skill("Python 3.14+") == "python"  # versions still strip

    def test_alias_k8s(self):
        assert normalize_skill("K8s") == "kubernetes"

    def test_alias_drf(self):
        assert normalize_skill("DRF") == "django rest framework"

    def test_alias_aws(self):
        assert normalize_skill("AWS") == "amazon web services"

    def test_alias_postgresql(self):
        assert normalize_skill("PostgreSQL") == "postgres"

    def test_alias_rest_apis(self):
        assert normalize_skill("REST APIs") == "rest api"

    def test_no_match_returns_lowered(self):
        assert normalize_skill("FastAPI") == "fastapi"

    def test_empty_string(self):
        assert normalize_skill("") == ""


class TestUkUsSpellings:
    def test_map_values_are_not_themselves_uk_spellings(self):
        assert not (set(_UK_TO_US.values()) & set(_UK_TO_US))

    def test_uk_spelling_canonicalizes_to_us_form(self):
        for uk, us in _UK_TO_US.items():
            assert normalize_skill(uk) == us

    def test_repeated_normalization_is_a_fixpoint(self):
        for uk in _UK_TO_US:
            once = normalize_skill(uk)
            assert normalize_skill(once) == once

    def test_version_and_punctuation_suffixes_still_apply(self):
        assert normalize_skill("query optimisation 2.0+") == "query optimization"
        assert normalize_skill("PostgreSQL 16") == "postgres"


class TestExtractSkillTokens:
    def test_single_skill(self):
        assert extract_skill_tokens("Python") == ["python"]

    def test_compound_with_colon(self):
        tokens = extract_skill_tokens("PostgreSQL: schema design, migrations")
        assert "postgres" in tokens

    def test_slash_separated(self):
        tokens = extract_skill_tokens("FastAPI/Django")
        assert "fastapi" in tokens
        assert "django" in tokens

    def test_version_stripped(self):
        tokens = extract_skill_tokens("Python 3.14+")
        assert tokens == ["python"]


class TestBuildSkillIndex:
    SAMPLE_SKILLS = [
        {
            "name": "Backend",
            "sub_categories": [
                {"name": "languages", "items": ["Python 3.14+"]},
                {"name": "frameworks", "items": ["FastAPI", "Django"]},
            ],
        },
        {
            "name": "Databases",
            "sub_categories": [
                {"name": "datastores", "items": ["PostgreSQL", "Redis"]},
            ],
        },
    ]

    def test_indexes_single_word_skills(self):
        index = build_skill_index(self.SAMPLE_SKILLS)
        assert "python" in index
        assert "fastapi" in index
        assert "django" in index
        assert "redis" in index

    def test_indexes_compound_tokens(self):
        index = build_skill_index(self.SAMPLE_SKILLS)
        assert "postgres" in index  # alias for PostgreSQL

    def test_metadata_preserved(self):
        index = build_skill_index(self.SAMPLE_SKILLS)
        assert index["python"]["category"] == "Backend"
        assert index["python"]["sub_category"] == "languages"
        assert index["python"]["original"] == "Python 3.14+"

    def test_additional_skills_indexed(self):
        additional = [
            {
                "name": "Kubernetes",
                "sub_categories": [
                    {"name": "tools", "items": ["deployment"]},
                ],
            }
        ]
        index = build_skill_index(self.SAMPLE_SKILLS, additional)
        assert "kubernetes" in index or "deployment" in index

    def test_empty_skills(self):
        index = build_skill_index([])
        assert index == {}

    def test_empty_items_do_not_poison_index(self):
        skills = [
            {
                "name": "Backend",
                "sub_categories": [
                    {"name": "languages", "items": ["", "  "]},
                ],
            }
        ]
        index = build_skill_index(skills)
        assert index == {}
