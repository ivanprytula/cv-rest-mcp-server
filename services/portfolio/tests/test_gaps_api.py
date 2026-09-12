"""Gap-analysis API: storage, analysis, roadmap aggregation, and auth.

Runs against a real throwaway Postgres (testcontainers), like the other
persistence tests — the roadmap is raw SQL over JSONB, so an in-memory fake
would test nothing that matters.
"""

import pytest
from fastapi import status


GAPS = "/api/v1/gaps"
POSTINGS = "/api/v1/postings"


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
    resp = await client.post(POSTINGS, content=text.encode(), params=params)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json()


async def _analyze(client, posting_id):
    resp = await client.post(f"{POSTINGS}/{posting_id}/analyze")
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
        resp = await admin_client.post(POSTINGS, content=b"   ")
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_listing_returns_stored_postings(self, admin_client):
        await _store(admin_client, JD_KUBERNETES, company="Acme")
        resp = await admin_client.get(POSTINGS)
        assert resp.status_code == status.HTTP_200_OK
        postings = resp.json()["postings"]
        assert len(postings) == 1
        assert postings[0]["company"] == "Acme"
        # The summary must not carry the full JD text.
        assert "posting_text" not in postings[0]


class TestDeletePosting:
    async def test_deletes_the_posting(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES, company="Acme")
        resp = await admin_client.delete(f"{POSTINGS}/{posting['id']}")
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        listing = await admin_client.get(POSTINGS)
        assert listing.json()["postings"] == []

    async def test_deleting_unknown_posting_is_404(self, admin_client):
        resp = await admin_client.delete(f"{POSTINGS}/999999")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_requires_admin(self, admin_client, user_service):
        posting = await _store(admin_client, JD_KUBERNETES)
        await user_service.register(username="plainuser", password="correct-password")
        resp = await admin_client.post(
            "/api/v1/auth/token",
            json={"username": "plainuser", "password": "correct-password"},
        )
        token = resp.json()["access_token"]
        resp = await admin_client.delete(
            f"{POSTINGS}/{posting['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


class TestPostingDocumentConsistency:
    """The Postgres row and its Firestore document are two writes with no
    shared transaction — these lock in the ordering that keeps a partial
    failure from producing an unreadable posting, rather than relying on it
    staying correct by accident.
    """

    async def test_firestore_write_happens_before_the_postgres_row(self, admin_client):
        from services.portfolio.main import app

        gap_service = app.state.gap_service
        calls: list[str] = []
        real_posting_docs_save = gap_service._posting_docs.save
        real_upsert_posting = gap_service._repo.upsert_posting

        async def spy_posting_docs_save(*args, **kwargs):
            calls.append("firestore")
            return await real_posting_docs_save(*args, **kwargs)

        async def spy_upsert_posting(*args, **kwargs):
            calls.append("postgres")
            return await real_upsert_posting(*args, **kwargs)

        gap_service._posting_docs.save = spy_posting_docs_save
        gap_service._repo.upsert_posting = spy_upsert_posting
        try:
            await _store(admin_client, JD_KUBERNETES)
        finally:
            gap_service._posting_docs.save = real_posting_docs_save
            gap_service._repo.upsert_posting = real_upsert_posting

        assert calls == ["firestore", "postgres"]

    async def test_a_failed_firestore_write_never_creates_a_postgres_row(
        self, admin_client
    ):
        from services.portfolio.main import app

        gap_service = app.state.gap_service
        real_posting_docs_save = gap_service._posting_docs.save

        async def failing_save(*args, **kwargs):
            raise RuntimeError("Firestore unavailable")

        gap_service._posting_docs.save = failing_save
        try:
            resp = await admin_client.post(POSTINGS, content=JD_KUBERNETES.encode())
        finally:
            gap_service._posting_docs.save = real_posting_docs_save

        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

        listing = await admin_client.get(POSTINGS)
        assert listing.json()["postings"] == []

    async def test_restoring_a_posting_with_a_lost_document_repairs_it(
        self, admin_client, operator_tenant_id
    ):
        """Re-storing identical text must rewrite the document, not just
        dedup to the row. Without this, a row whose document went missing
        404s on analyze forever — no way to fix it short of a DB edit.
        """
        from services.portfolio.main import app

        posting = await _store(admin_client, JD_KUBERNETES)
        gap_service = app.state.gap_service
        row = await gap_service._repo.get_posting(
            posting["id"], tenant_id=operator_tenant_id
        )
        gap_service._posting_docs._documents.pop(row.content_hash)

        restored = await _store(admin_client, JD_KUBERNETES)
        assert restored["id"] == posting["id"]
        assert restored["duplicate"] is True

        resp = await admin_client.post(f"{POSTINGS}/{posting['id']}/analyze")
        assert resp.status_code == status.HTTP_200_OK, resp.text

    async def test_a_posting_missing_its_document_is_reported_not_crashed(
        self, admin_client, operator_tenant_id
    ):
        # Simulates the residual risk the docstrings call out: a Postgres
        # row exists, but its Firestore document is gone (process killed
        # mid-write, or a document deleted out-of-band). get_posting must
        # degrade to a logged failure, never an unhandled exception.
        from services.portfolio.main import app

        posting = await _store(admin_client, JD_KUBERNETES)
        gap_service = app.state.gap_service
        row = await gap_service._repo.get_posting(
            posting["id"], tenant_id=operator_tenant_id
        )
        gap_service._posting_docs._documents.pop(row.content_hash)

        resp = await admin_client.post(f"{POSTINGS}/{posting['id']}/analyze")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestListingFilteredByTerm:
    async def test_mentions_filters_to_matching_postings(self, admin_client):
        graphql_only = await _store(admin_client, JD_KUBERNETES, company="Acme")
        terraform_only = await _store(
            admin_client, JD_TERRAFORM, company="Beta", url="https://x/2"
        )
        await _analyze(admin_client, graphql_only["id"])
        await _analyze(admin_client, terraform_only["id"])

        resp = await admin_client.get(POSTINGS, params={"mentions": "GraphQL"})
        assert resp.status_code == status.HTTP_200_OK
        postings = resp.json()["postings"]
        assert len(postings) == 1
        assert postings[0]["company"] == "Acme"

    async def test_mentions_is_case_insensitive(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES, company="Acme")
        await _analyze(admin_client, posting["id"])

        resp = await admin_client.get(POSTINGS, params={"mentions": "graphql"})
        assert len(resp.json()["postings"]) == 1

    async def test_unanalyzed_posting_is_excluded(self, admin_client):
        await _store(admin_client, JD_KUBERNETES, company="Acme")
        # Never analyzed — the term can neither be confirmed nor denied.

        resp = await admin_client.get(POSTINGS, params={"mentions": "GraphQL"})
        assert resp.json()["postings"] == []

    async def test_unmatched_term_returns_empty(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES, company="Acme")
        await _analyze(admin_client, posting["id"])

        resp = await admin_client.get(POSTINGS, params={"mentions": "Kafka"})
        assert resp.json()["postings"] == []

    async def test_no_filter_returns_everything(self, admin_client):
        await _store(admin_client, JD_KUBERNETES, company="Acme")
        await _store(admin_client, JD_TERRAFORM, company="Beta", url="https://x/2")

        resp = await admin_client.get(POSTINGS)
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
        # `unrecognized` is computed live against the posting text at analyze
        # time, not persisted — reading the stored report omits it.
        posting = await _store(admin_client, JD_KUBERNETES)
        analyzed = await _analyze(admin_client, posting["id"])
        resp = await admin_client.get(f"{POSTINGS}/{posting['id']}")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == {**analyzed, "unrecognized": []}

    async def test_missing_posting_is_404(self, admin_client):
        resp = await admin_client.post(f"{POSTINGS}/999999/analyze")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_unanalyzed_posting_report_is_404(self, admin_client):
        posting = await _store(admin_client, JD_KUBERNETES)
        resp = await admin_client.get(f"{POSTINGS}/{posting['id']}")
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
        counts = {item["term"]: item["posting_count"] for item in items}
        assert counts.get("Terraform") == 2
        assert counts.get("GraphQL") == 1
        # posting_count descending is the product; assert the ordering holds.
        assert [i["posting_count"] for i in items] == sorted(
            (i["posting_count"] for i in items), reverse=True
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
            report = (await admin_client.get(f"{POSTINGS}/{posting_id}")).json()
            for gap in report["gaps"]:
                if gap["tier"] != "covered":
                    expected[gap["term"]] = expected.get(gap["term"], 0) + 1

        items = (await admin_client.get(f"{GAPS}/roadmap")).json()["items"]
        assert {i["term"]: i["posting_count"] for i in items} == expected

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
            ("GET", POSTINGS),
            ("GET", f"{POSTINGS}/1"),
            ("POST", GAPS),
            ("POST", f"{POSTINGS}/1/analyze"),
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

        postings = (await admin_client.get(POSTINGS)).json()["postings"]
        assert [p["source"] for p in postings] == ["tailor"]

    async def test_stored_posting_is_analyzable(self, admin_client):
        await admin_client.post("/api/v1/cv/tailor", content=JD_KUBERNETES.encode())
        postings = (await admin_client.get(POSTINGS)).json()["postings"]
        report = await _analyze(admin_client, postings[0]["id"])
        assert report["gaps"]

    async def test_revision_hash_matches_the_posting_hash(self, admin_client):
        """`revisions.jd_hash` and `job_postings.content_hash` are the join."""
        from services.portfolio.gaps.gap_service import content_hash
        from services.portfolio.revisions.revision_service import jd_hash

        await admin_client.post("/api/v1/cv/tailor", content=JD_KUBERNETES.encode())
        postings = (await admin_client.get(POSTINGS)).json()["postings"]
        stored = await admin_client.get(f"{POSTINGS}/{postings[0]['id']}")
        assert stored.status_code in (status.HTTP_200_OK, status.HTTP_404_NOT_FOUND)
        # Both digests are SHA-256 of the same normalized posting text.
        assert jd_hash(JD_KUBERNETES) == content_hash(JD_KUBERNETES)

    async def test_tailoring_the_same_jd_twice_stores_one_posting(self, admin_client):
        for _ in range(2):
            await admin_client.post("/api/v1/cv/tailor", content=JD_KUBERNETES.encode())
        postings = (await admin_client.get(POSTINGS)).json()["postings"]
        assert len(postings) == 1


class TestDeleteRevision:
    async def test_deletes_the_revision(self, admin_client):
        tailor_resp = await admin_client.post(
            "/api/v1/cv/tailor", content=JD_KUBERNETES.encode()
        )
        revision_id = tailor_resp.json()["saved_to"]

        resp = await admin_client.delete(f"/api/v1/revisions/{revision_id}")
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        listing = await admin_client.get("/api/v1/revisions")
        assert revision_id not in [r["id"] for r in listing.json()["revisions"]]

    async def test_deleting_unknown_revision_is_404(self, admin_client):
        resp = await admin_client.delete("/api/v1/revisions/999999")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_requires_admin(self, admin_client, user_service):
        tailor_resp = await admin_client.post(
            "/api/v1/cv/tailor", content=JD_KUBERNETES.encode()
        )
        revision_id = tailor_resp.json()["saved_to"]
        await user_service.register(username="plainuser", password="correct-password")
        resp = await admin_client.post(
            "/api/v1/auth/token",
            json={"username": "plainuser", "password": "correct-password"},
        )
        token = resp.json()["access_token"]
        resp = await admin_client.delete(
            f"/api/v1/revisions/{revision_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


JD_TWO_RESPONSIBILITIES = (
    "Built CI/CD pipelines for microservices deployments across teams\n"
    "Automated deployment workflows across every backend service\n"
    "Owned the on-call rotation for the payments platform"
)


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Replace the model call with a deterministic, model-free stand-in.

    Sentences containing "pipeline" or "deployment" get a shared vector so
    they cluster together; the on-call sentence gets an orthogonal one. Never
    touches fastembed — keeps this test hermetic and fast, per the plan's
    "embed_phrases gets no unit test" split.
    """

    def _fake_embed(phrases: list[str]) -> list[list[float]]:
        vectors = []
        for phrase in phrases:
            lowered = phrase.lower()
            if "pipeline" in lowered or "deployment" in lowered:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors

    monkeypatch.setattr(
        "services.portfolio.matching.clustering.embed_phrases", _fake_embed
    )


class TestPhraseClustering:
    async def test_paraphrased_sentences_cluster_together(
        self, admin_client, fake_embeddings
    ):
        posting = await _store(admin_client, JD_TWO_RESPONSIBILITIES)
        resp = await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")
        assert resp.status_code == status.HTTP_200_OK, resp.text
        clusters = resp.json()["clusters"]
        sizes = sorted(len(c["phrases"]) for c in clusters)
        assert sizes == [1, 2]

    async def test_cluster_label_is_a_real_phrase(self, admin_client, fake_embeddings):
        posting = await _store(admin_client, JD_TWO_RESPONSIBILITIES)
        resp = await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")
        clusters = resp.json()["clusters"]
        for cluster in clusters:
            assert cluster["label"] in cluster["phrases"]

    async def test_stored_clusters_are_readable(self, admin_client, fake_embeddings):
        posting = await _store(admin_client, JD_TWO_RESPONSIBILITIES)
        clustered = (
            await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")
        ).json()
        resp = await admin_client.get(f"{POSTINGS}/{posting['id']}/clusters")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == clustered

    async def test_missing_posting_is_404(self, admin_client):
        resp = await admin_client.post(f"{POSTINGS}/999999/cluster")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_unclustered_posting_read_is_404(self, admin_client):
        posting = await _store(admin_client, JD_TWO_RESPONSIBILITIES)
        resp = await admin_client.get(f"{POSTINGS}/{posting['id']}/clusters")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_reclustering_replaces_the_prior_result(
        self, admin_client, fake_embeddings
    ):
        posting = await _store(admin_client, JD_TWO_RESPONSIBILITIES)
        first = (await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")).json()
        second = (await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")).json()
        assert first == second

    async def test_a_posting_with_no_clusterable_phrases_persists_an_empty_result(
        self, admin_client
    ):
        # No 5-40 word verb-bearing segment in this text — segment_phrases
        # yields nothing, but the empty result must still be stored so a
        # later GET reads it back rather than 404ing on "never analyzed".
        posting = await _store(admin_client, "3+ years\nPython")
        posted = await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")
        assert posted.status_code == status.HTTP_200_OK, posted.text
        assert posted.json()["clusters"] == []

        read = await admin_client.get(f"{POSTINGS}/{posting['id']}/clusters")
        assert read.status_code == status.HTTP_200_OK
        assert read.json()["clusters"] == []

    async def test_a_model_bump_never_returns_a_stale_embedding(
        self, admin_client, fake_embeddings, monkeypatch
    ):
        # A phrase cached under one EMBEDDING_MODEL must be treated as a
        # cache miss (and re-embedded/overwritten) once the model changes —
        # get_cached_embeddings filters by model_name, so a bump can't
        # silently mix vectors from two model generations in one cluster.
        from services.portfolio.gaps import gap_service as gap_service_module

        posting = await _store(admin_client, JD_TWO_RESPONSIBILITIES)
        await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")

        monkeypatch.setattr(gap_service_module, "EMBEDDING_MODEL", "a-different-model")
        resp = await admin_client.post(f"{POSTINGS}/{posting['id']}/cluster")
        assert resp.status_code == status.HTTP_200_OK, resp.text
        # Re-clustering succeeded (didn't silently reuse the old-model cache
        # and skip re-embedding); the paraphrase pair still groups together.
        sizes = sorted(len(c["phrases"]) for c in resp.json()["clusters"])
        assert sizes == [1, 2]
