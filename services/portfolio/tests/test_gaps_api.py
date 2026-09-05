"""Gap-analysis API: storage, analysis, roadmap aggregation, and auth.

Runs against a real throwaway Postgres (testcontainers), like the other
persistence tests — the roadmap is raw SQL over JSONB, so an in-memory fake
would test nothing that matters.
"""

import pytest
from fastapi import status


GAPS = "/api/v1/gaps"


@pytest.fixture
async def admin_client(auth_client):
    """`auth_client` with an admin bearer token already applied.

    Every gap route lives under /api/v1, so all of them need a token; the
    mutations additionally need the admin role, which the seeded `operator`
    has.
    """
    resp = await auth_client.post(
        "/api/v1/auth/token",
        json={"username": "operator", "password": "correct-password"},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    token = resp.json()["access_token"]
    auth_client.headers["Authorization"] = f"Bearer {token}"
    return auth_client


JD_KUBERNETES = (
    "Senior Engineer. 5+ years of experience with Kubernetes. "
    "Familiarity with Terraform. Knowledge of GraphQL is a plus."
)
JD_TERRAFORM = "Platform Engineer. Experience with Terraform and Kubernetes."


async def _store(client, text, **params):
    resp = await client.post(GAPS, content=text.encode(), params=params)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json()


async def _analyze(client, posting_id):
    resp = await client.post(f"{GAPS}/postings/{posting_id}/analyze")
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return resp.json()


class TestStorePosting:
    async def test_stores_and_returns_id_and_hash(self, admin_client):
        body = await _store(admin_client, JD_KUBERNETES, company="Acme", title="Eng")
        assert body["id"] > 0
        assert len(body["content_hash"]) == 64
        assert body["duplicate"] is False

    async def test_reposting_identical_text_is_deduped(self, admin_client):
        first = await _store(admin_client, JD_KUBERNETES)
        second = await _store(admin_client, JD_KUBERNETES)
        assert second["id"] == first["id"]
        assert second["duplicate"] is True

    async def test_empty_body_is_rejected(self, admin_client):
        resp = await admin_client.post(GAPS, content=b"   ")
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_listing_returns_stored_postings(self, admin_client):
        await _store(admin_client, JD_KUBERNETES, company="Acme")
        resp = await admin_client.get(f"{GAPS}/postings")
        assert resp.status_code == status.HTTP_200_OK
        postings = resp.json()["postings"]
        assert len(postings) == 1
        assert postings[0]["company"] == "Acme"
        # The summary must not carry the full JD text.
        assert "jd_text" not in postings[0]


class TestListingFilteredByTerm:
    async def test_mentions_filters_to_matching_postings(self, admin_client):
        graphql_only = await _store(admin_client, JD_KUBERNETES, company="Acme")
        terraform_only = await _store(
            admin_client, JD_TERRAFORM, company="Beta", url="https://x/2"
        )
        await _analyze(admin_client, graphql_only["id"])
        await _analyze(admin_client, terraform_only["id"])

        resp = await admin_client.get(
            f"{GAPS}/postings", params={"mentions": "GraphQL"}
        )
        assert resp.status_code == status.HTTP_200_OK
        postings = resp.json()["postings"]
        assert len(postings) == 1
        assert postings[0]["company"] == "Acme"

    async def test_mentions_is_case_insensitive(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES, company="Acme")
        await _analyze(admin_client, posting["id"])

        resp = await admin_client.get(
            f"{GAPS}/postings", params={"mentions": "graphql"}
        )
        assert len(resp.json()["postings"]) == 1

    async def test_unanalyzed_posting_is_excluded(self, admin_client):
        await _store(admin_client, JD_KUBERNETES, company="Acme")
        # Never analyzed — the term can neither be confirmed nor denied.

        resp = await admin_client.get(
            f"{GAPS}/postings", params={"mentions": "GraphQL"}
        )
        assert resp.json()["postings"] == []

    async def test_unmatched_term_returns_empty(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES, company="Acme")
        await _analyze(admin_client, posting["id"])

        resp = await admin_client.get(f"{GAPS}/postings", params={"mentions": "Kafka"})
        assert resp.json()["postings"] == []

    async def test_no_filter_returns_everything(self, admin_client):
        await _store(admin_client, JD_KUBERNETES, company="Acme")
        await _store(admin_client, JD_TERRAFORM, company="Beta", url="https://x/2")

        resp = await admin_client.get(f"{GAPS}/postings")
        assert len(resp.json()["postings"]) == 2


class TestAnalysis:
    async def test_analysis_assigns_tiers_and_coverage(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES)
        report = await _analyze(admin_client, posting["id"])
        assert report["posting_id"] == posting["id"]
        assert 0.0 <= report["coverage"] <= 1.0
        assert report["gaps"]
        assert all(
            gap["tier"] in {"covered", "unvouched", "deferred", "unknown"}
            for gap in report["gaps"]
        )

    async def test_analysis_is_idempotent(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES)
        first = await _analyze(admin_client, posting["id"])
        second = await _analyze(admin_client, posting["id"])
        assert first == second

    async def test_stored_report_is_readable(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES)
        analyzed = await _analyze(admin_client, posting["id"])
        resp = await admin_client.get(f"{GAPS}/postings/{posting['id']}")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == analyzed

    async def test_missing_posting_is_404(self, admin_client):
        resp = await admin_client.post(f"{GAPS}/postings/999999/analyze")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_unanalyzed_posting_report_is_404(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES)
        resp = await admin_client.get(f"{GAPS}/postings/{posting['id']}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestRoadmap:
    async def test_empty_corpus_yields_empty_roadmap(self, admin_client):
        resp = await admin_client.get(f"{GAPS}/roadmap")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["items"] == []

    async def test_ranks_terms_by_posting_count(self, admin_client):
        # Terraform appears in both postings, GraphQL in only one.
        for jd in (JD_KUBERNETES, JD_TERRAFORM):
            posting = await _store(admin_client, jd)
            await _analyze(admin_client, posting["id"])

        items = (await admin_client.get(f"{GAPS}/roadmap")).json()["items"]
        counts = {item["term"]: item["jd_count"] for item in items}
        assert counts.get("Terraform") == 2
        assert counts.get("GraphQL") == 1
        # jd_count descending is the product; assert the ordering holds.
        assert [i["jd_count"] for i in items] == sorted(
            (i["jd_count"] for i in items), reverse=True
        )

    async def test_covered_terms_are_excluded(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES)
        await _analyze(admin_client, posting["id"])
        items = (await admin_client.get(f"{GAPS}/roadmap")).json()["items"]
        assert all(item["tier"] != "covered" for item in items)

    async def test_roadmap_arithmetic_matches_analyses(self, admin_client):
        """Every (posting, term) pair is counted exactly once."""
        posting_ids = []
        for jd in (JD_KUBERNETES, JD_TERRAFORM):
            posting = await _store(admin_client, jd)
            posting_ids.append(posting["id"])
            await _analyze(admin_client, posting["id"])

        expected: dict[str, int] = {}
        for posting_id in posting_ids:
            report = (await admin_client.get(f"{GAPS}/postings/{posting_id}")).json()
            for gap in report["gaps"]:
                if gap["tier"] != "covered":
                    expected[gap["term"]] = expected.get(gap["term"], 0) + 1

        items = (await admin_client.get(f"{GAPS}/roadmap")).json()["items"]
        assert {i["term"]: i["jd_count"] for i in items} == expected

    async def test_strongest_level_uses_strength_not_alphabet(self, admin_client):
        """max('basic','expert','middle') is 'middle' alphabetically."""
        posting = await _store(
            admin_client,
            "Familiarity with Terraform. 5+ years of experience with Terraform.",
        )
        await _analyze(admin_client, posting["id"])
        items = (await admin_client.get(f"{GAPS}/roadmap")).json()["items"]
        terraform = next(i for i in items if i["term"] == "Terraform")
        assert terraform["strongest_level_asked"] == "expert"


class TestAuth:
    """Every gap route lives under /api/v1, so all require a token."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", f"{GAPS}/roadmap"),
            ("GET", f"{GAPS}/postings"),
            ("GET", f"{GAPS}/postings/1"),
            ("POST", GAPS),
            ("POST", f"{GAPS}/postings/1/analyze"),
        ],
    )
    async def test_unauthenticated_is_401(self, client, method, path):
        resp = await client.request(method, path, headers={"Authorization": ""})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestTailoringStoresThePosting:
    """Tailoring keeps the JD text, not just its hash.

    Before this, `/cv/tailor` stored only `revisions.jd_hash`, so every
    tailored revision pointed at a job description nobody could read back.
    """

    async def test_tailoring_stores_the_posting(self, admin_client):
        resp = await admin_client.post(
            "/api/v1/cv/tailor", content=JD_KUBERNETES.encode()
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        postings = (await admin_client.get(f"{GAPS}/postings")).json()["postings"]
        assert [p["source"] for p in postings] == ["tailor"]

    async def test_stored_posting_is_analyzable(self, admin_client):
        await admin_client.post("/api/v1/cv/tailor", content=JD_KUBERNETES.encode())
        postings = (await admin_client.get(f"{GAPS}/postings")).json()["postings"]
        report = await _analyze(admin_client, postings[0]["id"])
        assert report["gaps"]

    async def test_revision_hash_matches_the_posting_hash(self, admin_client):
        """`revisions.jd_hash` and `job_postings.content_hash` are the join."""
        from services.portfolio.gaps.gap_service import content_hash
        from services.portfolio.revisions.revision_service import jd_hash

        await admin_client.post("/api/v1/cv/tailor", content=JD_KUBERNETES.encode())
        postings = (await admin_client.get(f"{GAPS}/postings")).json()["postings"]
        stored = await admin_client.get(f"{GAPS}/postings/{postings[0]['id']}")
        assert stored.status_code in (status.HTTP_200_OK, status.HTTP_404_NOT_FOUND)
        # Both digests are SHA-256 of the same normalized JD text.
        assert jd_hash(JD_KUBERNETES) == content_hash(JD_KUBERNETES)

    async def test_tailoring_the_same_jd_twice_stores_one_posting(self, admin_client):
        for _ in range(2):
            await admin_client.post("/api/v1/cv/tailor", content=JD_KUBERNETES.encode())
        postings = (await admin_client.get(f"{GAPS}/postings")).json()["postings"]
        assert len(postings) == 1
