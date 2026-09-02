"""Tests for app.matching.matcher."""

from services.portfolio.matching.matcher import (
    _fuzzy_score,
    _substring_score,
    filter_atoms_by_level,
    match_skills,
    sort_atoms_by_priority,
)
from services.portfolio.matching.taxonomy import build_skill_index


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


class TestSubstringScore:
    def test_exact(self):
        assert _substring_score("python", "python") == 1.0

    def test_contained_at_start_is_full_match(self):
        assert _substring_score("python", "python 3") == 1.0

    def test_contained_in_middle_is_full_match(self):
        assert _substring_score("rest", "django rest framework") == 1.0

    def test_no_match(self):
        assert _substring_score("java", "python") == 0.0

    def test_typo_gets_partial_score(self):
        assert _substring_score("pyton", "python") == 0.8


class TestFuzzyScore:
    def test_identical(self):
        assert _fuzzy_score("python", "python") == 1.0

    def test_similar(self):
        score = _fuzzy_score("pyton", "python")
        assert score >= 0.8
        assert score == 10.0 / 11.0

    def test_dissimilar(self):
        assert _fuzzy_score("java", "python") < 0.5


class TestMatchSkills:
    def test_exact_match(self):
        matches = match_skills(["python"], INDEX)
        assert len(matches) >= 1
        assert matches[0].score == 1.0

    def test_alias_match(self):
        matches = match_skills(["kubernetes"], INDEX)
        # kubernetes is not in the sample CV, so no match
        assert len(matches) == 0

    def test_fuzzy_match(self):
        matches = match_skills(["pyton"], INDEX)
        assert len(matches) >= 1
        assert matches[0].score >= 0.8

    def test_no_match_below_threshold(self):
        matches = match_skills(["marketing"], INDEX, threshold=0.8)
        assert len(matches) == 0

    def test_sorted_by_score(self):
        matches = match_skills(["python", "pyton"], INDEX)
        if len(matches) >= 2:
            assert matches[0].score >= matches[1].score

    def test_match_metadata(self):
        matches = match_skills(["python"], INDEX)
        assert len(matches) >= 1
        m = matches[0]
        assert m.category == "Backend"
        assert m.sub_category == "languages"

    def test_empty_input(self):
        assert match_skills([], INDEX) == []

    def test_empty_cv_item_does_not_match_everything(self):
        skills = [
            {
                "name": "Backend",
                "sub_categories": [{"name": "languages", "items": [""]}],
            }
        ]
        index = build_skill_index(skills)
        assert index == {}
        assert match_skills(["python"], index) == []

    def test_threshold_filtering(self):
        matches = match_skills(["pyton"], INDEX, threshold=0.99)
        assert len(matches) == 0


_E = {"atom": "A", "level": "expert", "priority": "high"}
_M = {"atom": "B", "level": "middle", "priority": "medium"}
_B = {"atom": "C", "level": "basic", "priority": "low"}


class TestFilterAtomsByLevel:
    def test_none_keeps_everything(self):
        assert filter_atoms_by_level([_E, _M, _B], None) == [_E, _M, _B]

    def test_expert_requirement_keeps_only_expert(self):
        assert filter_atoms_by_level([_E, _M, _B], "expert") == [_E]

    def test_middle_requirement_keeps_expert_and_middle(self):
        assert filter_atoms_by_level([_E, _M, _B], "middle") == [_E, _M]

    def test_basic_requirement_keeps_all(self):
        assert filter_atoms_by_level([_E, _M, _B], "basic") == [_E, _M, _B]

    def test_unknown_bank_level_never_qualifies(self):
        weird = {"atom": "W", "level": "guru", "priority": "high"}
        assert filter_atoms_by_level([weird, _E], "middle") == [_E]

    def test_missing_level_never_qualifies(self):
        bare = {"atom": "D", "priority": "medium"}
        assert filter_atoms_by_level([bare, _M], "middle") == [_M]

    def test_stable_order_on_filter(self):
        atoms = [_E, _M, _B, _M]
        assert filter_atoms_by_level(atoms, "expert") == [_E]


class TestSortAtomsByPriority:
    def test_sorts_high_to_low(self):
        atoms = [_B, _E, _M]
        assert sort_atoms_by_priority(atoms) == [_E, _M, _B]

    def test_stable_within_band(self):
        a_high = {"atom": "a", "priority": "high"}
        b_high = {"atom": "b", "priority": "high"}
        assert sort_atoms_by_priority([b_high, a_high]) == [b_high, a_high]

    def test_unknown_priority_sinks_to_bottom(self):
        no = {"atom": "none", "priority": ""}
        assert sort_atoms_by_priority([no, _E]) == [_E, no]
