"""Tests for app.matching.baseline (skill bank loader, atom index, lazy cache)."""

import json
from pathlib import Path

import pytest

from services.portfolio.constants import PROJECT_ROOT
from services.portfolio.matching.baseline import (
    ATOM_OPTIONAL_KEYS,
    ATOM_REQUIRED_KEYS,
    BaselineError,
    build_atom_index,
    get_baseline,
    load_baseline,
)
from services.portfolio.matching.taxonomy import normalize_skill


VALID_ATOMS = [
    {
        "atom": "Python",
        "group_id": "backend",
        "level": "expert",
        "priority": "high",
        "category_hint": "Backend development > languages",
    },
    {
        "atom": "Redis",
        "group_id": "databases",
        "level": "basic",
        "priority": "low",
        "category_hint": "Databases and data processing > datastores",
    },
]


def _write(tmp_path, obj) -> Path:
    path = tmp_path / "cv_baseline.json"
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def _bank(*atoms) -> dict:
    return {"_schema_version": "1", "_design_notes": "test", "skills": list(atoms)}


class TestLoadBaseline:
    def test_loads_valid_bank(self, tmp_path):
        path = _write(tmp_path, _bank(*VALID_ATOMS))
        atoms = load_baseline(path)
        assert len(atoms) == 2
        assert atoms[0]["atom"] == "Python"
        assert set(atoms[0]) == {
            "atom",
            "group_id",
            "level",
            "priority",
            "category_hint",
        }

    def test_missing_file(self, tmp_path):
        with pytest.raises(BaselineError, match="not found"):
            load_baseline(tmp_path / "missing.json")

    def test_bad_json(self, tmp_path):
        path = tmp_path / "cv_baseline.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(BaselineError, match="valid JSON"):
            load_baseline(path)

    def test_not_an_object(self, tmp_path):
        path = _write(tmp_path, ["skills"])
        with pytest.raises(BaselineError, match="JSON object"):
            load_baseline(path)

    def test_empty_skills_list(self, tmp_path):
        path = _write(tmp_path, {"skills": []})
        with pytest.raises(BaselineError, match="non-empty 'skills'"):
            load_baseline(path)

    def test_missing_required_key(self, tmp_path):
        bad = dict(VALID_ATOMS[0])
        del bad["priority"]
        path = _write(tmp_path, _bank(bad))
        with pytest.raises(BaselineError, match="missing keys"):
            load_baseline(path)

    def test_invalid_level(self, tmp_path):
        bad = dict(VALID_ATOMS[0], level="guru")
        path = _write(tmp_path, _bank(bad))
        with pytest.raises(BaselineError, match="invalid level"):
            load_baseline(path)

    def test_invalid_priority(self, tmp_path):
        bad = dict(VALID_ATOMS[0], priority="urgent")
        path = _write(tmp_path, _bank(bad))
        with pytest.raises(BaselineError, match="invalid priority"):
            load_baseline(path)

    def test_empty_atom_name(self, tmp_path):
        bad = dict(VALID_ATOMS[0], atom="   ")
        path = _write(tmp_path, _bank(bad))
        with pytest.raises(BaselineError, match="empty 'atom'"):
            load_baseline(path)

    def test_atom_too_long(self, tmp_path):
        bad = dict(VALID_ATOMS[0], atom="x" * 61)
        path = _write(tmp_path, _bank(bad))
        with pytest.raises(BaselineError, match="60-char"):
            load_baseline(path)

    def test_hint_missing_separator(self, tmp_path):
        bad = dict(VALID_ATOMS[0], category_hint="Backend development")
        path = _write(tmp_path, _bank(bad))
        with pytest.raises(BaselineError, match="Group > Sub"):
            load_baseline(path)

    def test_duplicate_atoms(self, tmp_path):
        path = _write(tmp_path, _bank(VALID_ATOMS[0], VALID_ATOMS[0]))
        with pytest.raises(BaselineError, match="duplicate atoms"):
            load_baseline(path)

    def test_deferred_pool_is_ignored(self, tmp_path):
        raw = {
            "_schema_version": "1",
            "skills": [VALID_ATOMS[0]],
            "deferred": [
                {
                    "atom": "Fortran",
                    "level": "expert",
                    "priority": "high",
                    "category_hint": "Backend development > languages",
                }
            ],
        }
        atoms = load_baseline(path=_write(tmp_path, raw))
        assert [a["atom"] for a in atoms] == ["Python"]


class TestBuildAtomIndex:
    def test_indexes_canonical_and_normalized(self):
        index = build_atom_index(VALID_ATOMS)
        assert "python" in index
        assert "redis" in index
        assert index["python"]["atom"] == "Python"

    def test_aliases_resolve_to_same_atom(self):
        atoms = [
            dict(
                VALID_ATOMS[0],
                aliases=["claude code cli"],
            )
        ]
        index = build_atom_index(atoms)
        assert index["claude code cli"]["atom"] == "Python"

    def test_canonical_name_wins_over_alias(self):
        # An atom's own name is authoritative: "Casbin" as an atom must not be
        # shadowed by an "API security" atom's "Casbin" alias.
        atoms = [
            dict(VALID_ATOMS[0], atom="API security", aliases=["casbin"]),
            dict(VALID_ATOMS[0], atom="Casbin"),
        ]
        index = build_atom_index(atoms)
        assert index["casbin"]["atom"] == "Casbin"

    def test_empty_atoms(self):
        assert build_atom_index([]) == {}


class TestGetBaseline:
    def test_resolves_default_path_via_settings(self, tmp_path, monkeypatch):
        from services.portfolio.settings import settings

        path = tmp_path / "bank.json"
        path.write_text(json.dumps(_bank(*VALID_ATOMS)), encoding="utf-8")
        monkeypatch.setattr(settings, "cv_baseline_path", path)
        atoms = get_baseline()
        assert atoms[0]["atom"] == "Python"

    def test_caches_same_file(self, tmp_path):
        path = tmp_path / "bank.json"
        path.write_text(json.dumps(_bank(*VALID_ATOMS)), encoding="utf-8")
        first = get_baseline(path)
        second = get_baseline(path)
        assert first is second

    def test_reloads_after_modification(self, tmp_path):
        path = tmp_path / "bank.json"
        path.write_text(json.dumps(_bank(VALID_ATOMS[0])), encoding="utf-8")
        assert [a["atom"] for a in get_baseline(path)] == ["Python"]
        path.write_text(
            json.dumps(_bank(VALID_ATOMS[0], VALID_ATOMS[1])), encoding="utf-8"
        )
        new = get_baseline(path)
        assert len(new) == 2

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(BaselineError, match="not found"):
            get_baseline(tmp_path / "nope.json")


class TestRealBankStructuralOnly:
    """Structural smoke checks against the operator's data/cv_baseline.json.

    No assertions on wording, names, or counts (those are operator content).
    """

    def test_atoms_have_required_keys_and_shape(self):
        path = PROJECT_ROOT / "data" / "cv_baseline.json"
        atoms = load_baseline(path)
        assert atoms
        expected = ATOM_REQUIRED_KEYS | set(ATOM_OPTIONAL_KEYS)
        for atom in atoms:
            assert set(atom) == expected
            assert atom["level"] in {"expert", "middle", "basic"}
            assert atom["priority"] in {"high", "medium", "low"}
            assert " > " in atom["category_hint"]

    def test_atom_names_are_unique(self):
        path = PROJECT_ROOT / "data" / "cv_baseline.json"
        atoms = load_baseline(path)
        names = [a["atom"] for a in atoms]
        assert len(names) == len(set(names))

    def test_aliases_do_not_clash_with_canonical_atoms(self):
        path = PROJECT_ROOT / "data" / "cv_baseline.json"
        atoms = load_baseline(path)
        index = build_atom_index(atoms)
        # Every atom's canonical form must resolve back to itself — an alias
        # collision would silently shadow a canonical key.
        for atom in atoms:
            canonical_key = normalize_skill(atom["atom"])
            resolved = index.get(canonical_key)
            assert resolved is not None and resolved["atom"] == atom["atom"]
