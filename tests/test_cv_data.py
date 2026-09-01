import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.constants import EXAMPLE_CV_PATH
from app.cv_data import CVData, SkillCategory, SkillSubCategory, load_cv_data


def test_cv_data_loads_successfully():
    # Structural smoke against the shipped example — never the personal file.
    data = load_cv_data(EXAMPLE_CV_PATH)
    assert isinstance(data, dict)
    assert isinstance(data["experience"], list)


def test_cv_data_schema_validation(synthetic_cv_path, synthetic_cv):
    cv = CVData(**load_cv_data(synthetic_cv_path))
    assert cv.name == synthetic_cv["name"]
    assert len(cv.experience) == len(synthetic_cv["experience"])
    assert [job.company for job in cv.experience] == ["Beta Corp", "Alpha Corp"]
    assert cv.education[0].degree == "BSc Testing"


def test_cv_data_accepts_minimal_fields():
    cv = CVData()
    assert cv.name == ""
    assert cv.skills == []
    assert cv.experience == []


def test_cv_data_accepts_extra_fields():
    cv = CVData(custom_field="value")
    assert cv.model_extra == {"custom_field": "value"}


def test_cv_data_rejects_invalid_type():
    invalid_fields: dict[str, Any] = {"name": 123}
    with pytest.raises(ValidationError):
        CVData(**invalid_fields)


def test_load_cv_data_wraps_single_education():
    raw = {
        "name": "Test",
        "education": {"degree": "BSc", "institution": "Uni", "year": "2020"},
    }
    result = load_cv_data_from_raw(raw)
    assert isinstance(result["education"], list)
    assert result["education"][0]["degree"] == "BSc"


def test_load_cv_data_keeps_list_education():
    raw = {
        "name": "Test",
        "education": [{"degree": "BSc", "institution": "Uni", "year": "2020"}],
    }
    result = load_cv_data_from_raw(raw)
    assert isinstance(result["education"], list)
    assert len(result["education"]) == 1


def test_load_cv_data_minimal_json():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({}, f)
        path = Path(f.name)
    try:
        result = load_cv_data(path)
        assert result["name"] == ""
        assert result["skills"] == []
    finally:
        path.unlink()


def test_load_cv_data_missing_file():
    with pytest.raises(FileNotFoundError):
        load_cv_data(Path("/nonexistent/path/cv.json"))


def test_load_cv_data_invalid_json_type():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("[]")
        path = Path(f.name)
    try:
        with pytest.raises(ValueError, match="must be a JSON object"):
            load_cv_data(path)
    finally:
        path.unlink()


def test_load_cv_data_invalid_schema_raises_readable_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": 123}), encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_cv_data(path)
    message = str(exc_info.value)
    assert "CV data validation failed" in message
    assert "name" in message


def load_cv_data_from_raw(raw: dict) -> dict:
    if isinstance(raw.get("education"), dict):
        raw["education"] = [raw["education"]]
    cv = CVData(**raw)
    return cv.model_dump()


def test_skill_category_with_sub_categories():
    cat = SkillCategory(
        name="Backend",
        sub_categories=[
            SkillSubCategory(name="languages", items=["Python"]),
            SkillSubCategory(name="frameworks", items=["FastAPI"]),
        ],
    )
    assert cat.name == "Backend"
    assert len(cat.sub_categories) == 2
    assert cat.sub_categories[0].items == ["Python"]


def test_skill_category_empty_sub_categories():
    cat = SkillCategory(name="Testing")
    assert cat.sub_categories == []


def test_cv_data_skills_uses_skill_category():
    cv = CVData(
        skills=[
            {
                "name": "Backend",
                "sub_categories": [
                    {"name": "languages", "items": ["Python"]},
                ],
            }
        ]
    )
    assert len(cv.skills) == 1
    assert cv.skills[0].name == "Backend"
    assert cv.skills[0].sub_categories[0].name == "languages"
