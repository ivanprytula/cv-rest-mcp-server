"""Operator documents: CRUD, validation, and the file fallback.

The fallback is the load-bearing behaviour here — without it local dev
needs Postgres to render a CV at all — so it gets tested directly rather
than only through the happy path.
"""

import json

import pytest
from fastapi import status


DOCS = "/api/v1/documents"


@pytest.fixture
async def admin_client(auth_client):
    resp = await auth_client.post(
        "/api/v1/auth/token",
        json={"username": "operator", "password": "correct-password"},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    auth_client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return auth_client


def _bank(atom="Python"):
    return {
        "skills": [
            {
                "atom": atom,
                "group_id": "backend",
                "level": "expert",
                "priority": "high",
                "category_hint": "Backend development > languages",
            }
        ],
        "deferred": [],
    }


class TestReadWrite:
    async def test_write_then_read_round_trips(self, admin_client):
        payload = _bank("Rust")
        resp = await admin_client.put(f"{DOCS}/skill_bank", json=payload)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()["version"] >= 1

        read = await admin_client.get(f"{DOCS}/skill_bank")
        assert read.status_code == status.HTTP_200_OK
        assert read.json()["skills"][0]["atom"] == "Rust"

    async def test_version_increments_on_each_write(self, admin_client):
        first = (await admin_client.put(f"{DOCS}/skill_bank", json=_bank("A"))).json()
        second = (await admin_client.put(f"{DOCS}/skill_bank", json=_bank("B"))).json()
        assert second["version"] == first["version"] + 1

    async def test_listing_reports_stored_versions(self, admin_client):
        await admin_client.put(f"{DOCS}/skill_bank", json=_bank())
        body = (await admin_client.get(DOCS)).json()
        assert "skill_bank" in body["versions"]
        assert set(body["kinds"]) == {"cv", "skill_bank", "jd_vocabulary"}

    async def test_unknown_kind_is_rejected(self, admin_client):
        resp = await admin_client.get(f"{DOCS}/not_a_kind")
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestValidation:
    """A document that would break matching must not reach storage."""

    async def test_bank_without_skills_is_rejected(self, admin_client):
        resp = await admin_client.put(f"{DOCS}/skill_bank", json={"skills": []})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_bank_atom_missing_keys_is_rejected(self, admin_client):
        resp = await admin_client.put(
            f"{DOCS}/skill_bank", json={"skills": [{"atom": "Python"}]}
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_vocabulary_without_terms_is_rejected(self, admin_client):
        resp = await admin_client.put(f"{DOCS}/jd_vocabulary", json={"terms": []})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_valid_vocabulary_is_accepted(self, admin_client):
        resp = await admin_client.put(
            f"{DOCS}/jd_vocabulary",
            json={"terms": [{"term": "Rust", "group_id": "backend"}]},
        )
        assert resp.status_code == status.HTTP_200_OK


class TestFileFallback:
    """Reads fall back to the on-disk JSON when the DB has no row."""

    async def test_read_falls_back_to_file(self, admin_client, tailor_settings):
        # Nothing was written for skill_bank, so this comes from the file the
        # `tailor_settings` fixture points cv_baseline_path at.
        resp = await admin_client.get(f"{DOCS}/skill_bank")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["skills"]

    async def test_db_row_wins_over_file(self, admin_client):
        await admin_client.put(f"{DOCS}/skill_bank", json=_bank("OnlyInDb"))
        body = (await admin_client.get(f"{DOCS}/skill_bank")).json()
        assert [a["atom"] for a in body["skills"]] == ["OnlyInDb"]

    async def test_missing_row_and_missing_file_is_404(
        self, admin_client, monkeypatch, tmp_path
    ):
        from services.portfolio.settings import settings

        monkeypatch.setattr(settings, "cv_data_path", tmp_path / "absent.json")
        resp = await admin_client.get(f"{DOCS}/cv")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestAnalysisUsesStoredDocuments:
    """An edited document takes effect on the next analysis, no redeploy."""

    async def test_edited_vocabulary_changes_the_report(self, admin_client):
        stored = await admin_client.post(
            "/api/v1/gaps", content=b"We need Rust and Elixir experience."
        )
        posting_id = stored.json()["id"]

        # Baseline: neither term is known, so nothing is found.
        before = (
            await admin_client.post(f"/api/v1/gaps/postings/{posting_id}/analyze")
        ).json()
        assert not any(g["term"] == "Rust" for g in before["gaps"])

        # Teach the vocabulary about Rust, then re-analyse.
        await admin_client.put(
            f"{DOCS}/jd_vocabulary",
            json={"terms": [{"term": "Rust", "group_id": "backend"}]},
        )
        after = (
            await admin_client.post(f"/api/v1/gaps/postings/{posting_id}/analyze")
        ).json()
        rust = next(g for g in after["gaps"] if g["term"] == "Rust")
        assert rust["tier"] == "unknown"


class TestSeeding:
    async def test_seed_is_idempotent_and_does_not_clobber(
        self, admin_client, tmp_path
    ):
        from services.portfolio.documents.document_row import KIND_SKILL_BANK
        from services.portfolio.documents.document_service import DocumentService
        from services.portfolio.main import app

        service: DocumentService = app.state.document_service
        await service.write(KIND_SKILL_BANK, _bank("Edited"))

        seed_file = tmp_path / "bank.json"
        seed_file.write_text(json.dumps(_bank("FromFile")), encoding="utf-8")
        await service.seed_from_files({KIND_SKILL_BANK: seed_file})

        stored = await service.read(KIND_SKILL_BANK)
        assert stored is not None
        assert stored["skills"][0]["atom"] == "Edited"


class TestAuth:
    @pytest.mark.parametrize(
        ("method", "path"),
        [("GET", DOCS), ("GET", f"{DOCS}/cv"), ("PUT", f"{DOCS}/cv")],
    )
    async def test_unauthenticated_is_401(self, client, method, path):
        resp = await client.request(method, path, headers={"Authorization": ""})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestRevert:
    """DELETE drops the stored row; the document still resolves from file."""

    async def test_revert_restores_the_file_content(self, admin_client):
        await admin_client.put(f"{DOCS}/skill_bank", json=_bank("OnlyInDb"))
        assert (await admin_client.get(f"{DOCS}/skill_bank")).json()["skills"][0][
            "atom"
        ] == "OnlyInDb"

        resp = await admin_client.delete(f"{DOCS}/skill_bank")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["reverted"] is True

        # Still readable — now from the file, not the DB.
        after = await admin_client.get(f"{DOCS}/skill_bank")
        assert after.status_code == status.HTTP_200_OK
        assert [a["atom"] for a in after.json()["skills"]] != ["OnlyInDb"]

    async def test_reverting_an_unstored_document_is_not_an_error(self, admin_client):
        resp = await admin_client.delete(f"{DOCS}/jd_vocabulary")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["reverted"] is False

    async def test_revert_clears_the_reported_version(self, admin_client):
        await admin_client.put(f"{DOCS}/skill_bank", json=_bank())
        await admin_client.delete(f"{DOCS}/skill_bank")
        assert "skill_bank" not in (await admin_client.get(DOCS)).json()["versions"]

    async def test_revert_requires_authentication(self, client):
        resp = await client.delete(f"{DOCS}/cv", headers={"Authorization": ""})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestKindsAreDataDriven:
    """Adding a document kind is a one-line change, not a code change."""

    async def test_route_pattern_matches_declared_kinds(self):
        from services.portfolio.documents.document_row import DOCUMENT_KINDS
        from services.portfolio.documents.routes import kind_path

        # The path pattern is derived, so it cannot drift from the tuple.
        for kind in DOCUMENT_KINDS:
            assert kind_path.metadata[0].pattern.strip("^$").split("|").count(kind) >= 0
            assert kind in kind_path.metadata[0].pattern

    async def test_kind_without_a_validator_is_stored_as_is(self, admin_client):
        """A new kind needs no schema — only kinds with one are checked."""
        from services.portfolio.documents.document_service import DocumentService
        from services.portfolio.main import app

        service: DocumentService = app.state.document_service
        assert await service.write("custom_notes", {"anything": [1, 2, 3]}) == 1
        assert await service.read("custom_notes") == {"anything": [1, 2, 3]}
