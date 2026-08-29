"""Tests for app.matching.selector."""

from app.matching.selector import reorder_skill_categories, reorder_skills


class TestReorderSkills:
    def test_matched_first(self):
        items = [
            {"items": ["A", "B", "C"]},
        ]
        result = reorder_skills(items, {"b"})
        assert result[0]["items"] == ["B", "A", "C"]

    def test_all_matched(self):
        items = [{"items": ["A", "B"]}]
        result = reorder_skills(items, {"a", "b"})
        assert result[0]["items"] == ["A", "B"]

    def test_none_matched(self):
        items = [{"items": ["A", "B"]}]
        result = reorder_skills(items, set())
        assert result[0]["items"] == ["A", "B"]

    def test_empty_items(self):
        result = reorder_skills([{"items": []}], {"a"})
        assert result == []

    def test_drops_empty_categories(self):
        items = [{"items": ["A"]}]
        result = reorder_skills(items, set())
        # "A" is not matched, but still present (not dropped)
        assert len(result) == 1

    def test_multiple_categories(self):
        items = [
            {"items": ["X", "Y"]},
            {"items": ["A", "B"]},
        ]
        result = reorder_skills(items, {"a"})
        assert result[0]["items"] == ["X", "Y"]  # no matches here
        assert result[1]["items"] == ["A", "B"]  # A matched, moved first


class TestReorderSkillCategories:
    def test_reorders_within_subcategories(self):
        categories = [
            {
                "name": "Backend",
                "sub_categories": [
                    {"name": "languages", "items": ["Python", "Java"]},
                    {"name": "frameworks", "items": ["FastAPI", "Spring"]},
                ],
            }
        ]
        result = reorder_skill_categories(categories, {"python", "fastapi"})
        langs = result[0]["sub_categories"][0]["items"]
        assert langs[0] == "Python"
        fw = result[0]["sub_categories"][1]["items"]
        assert fw[0] == "FastAPI"

    def test_preserves_category_structure(self):
        categories = [
            {
                "name": "Backend",
                "sub_categories": [
                    {"name": "languages", "items": ["Python"]},
                ],
            }
        ]
        result = reorder_skill_categories(categories, set())
        assert result[0]["name"] == "Backend"
        assert result[0]["sub_categories"][0]["name"] == "languages"
