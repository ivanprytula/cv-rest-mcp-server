"""ATS board sync orchestration — GapService.sync_board / refresh_all_boards.

Runs against a real throwaway Postgres (testcontainers), like the other
persistence tests — the etag cache and close-missing UPDATE are real SQL,
not something an in-memory fake would exercise honestly. HTTP itself is
mocked (httpx.MockTransport): this suite never makes a live ATS call.
"""

import httpx
import pytest

from services.portfolio.main import app


BANK = [
    {
        "atom": "Kubernetes",
        "group_id": "backend",
        "level": "middle",
        "priority": "high",
        "category_hint": "Backend development > infra",
    }
]
LIVE_CV = {"skills": []}


def _greenhouse_transport(jobs):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": jobs}, headers={"etag": '"v1"'})

    return handler


@pytest.fixture
def gap_service(user_service):
    return app.state.gap_service


class TestSyncBoard:
    async def test_new_posting_is_synced_and_counted(self, gap_service, monkeypatch):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                _greenhouse_transport(
                    [
                        {
                            "id": 1,
                            "title": "Backend Engineer",
                            "content": "Kubernetes required.",
                            "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                        }
                    ]
                )
            )
        )
        counts = await gap_service.sync_board(
            source="greenhouse",
            company_slug="acme",
            client=client,
            analysis_inputs=(BANK, [], []),
            live_cv=LIVE_CV,
        )
        assert counts["new"] == 1
        assert counts["errors"] == 0

        postings = await gap_service.list_postings()
        assert len(postings) == 1
        assert postings[0].company == ""

    async def test_second_sync_with_same_payload_is_unchanged(self, gap_service):
        jobs = [
            {
                "id": 2,
                "title": "SRE",
                "content": "Kubernetes required.",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
            }
        ]
        client1 = httpx.AsyncClient(
            transport=httpx.MockTransport(_greenhouse_transport(jobs))
        )
        await gap_service.sync_board(
            source="greenhouse",
            company_slug="acme2",
            client=client1,
            analysis_inputs=None,
            live_cv=None,
        )
        client2 = httpx.AsyncClient(
            transport=httpx.MockTransport(_greenhouse_transport(jobs))
        )
        counts = await gap_service.sync_board(
            source="greenhouse",
            company_slug="acme2",
            client=client2,
            analysis_inputs=None,
            live_cv=None,
        )
        assert counts["unchanged"] == 1
        assert counts["new"] == 0

    async def test_posting_absent_from_refetch_is_closed(self, gap_service):
        client1 = httpx.AsyncClient(
            transport=httpx.MockTransport(
                _greenhouse_transport(
                    [
                        {
                            "id": 3,
                            "title": "Eng",
                            "content": "text",
                            "absolute_url": "https://x/3",
                        }
                    ]
                )
            )
        )
        await gap_service.sync_board(
            source="greenhouse",
            company_slug="acme3",
            client=client1,
            analysis_inputs=None,
            live_cv=None,
        )
        client2 = httpx.AsyncClient(
            transport=httpx.MockTransport(_greenhouse_transport([]))
        )
        counts = await gap_service.sync_board(
            source="greenhouse",
            company_slug="acme3",
            client=client2,
            analysis_inputs=None,
            live_cv=None,
        )
        assert counts["closed"] == 1

    async def test_unknown_source_returns_error_count(self, gap_service):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_greenhouse_transport([]))
        )
        counts = await gap_service.sync_board(
            source="workday",
            company_slug="acme",
            client=client,
            analysis_inputs=None,
            live_cv=None,
        )
        assert counts["errors"] == 1

    async def test_fetch_failure_does_not_raise(self, gap_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        counts = await gap_service.sync_board(
            source="greenhouse",
            company_slug="down-board",
            client=client,
            analysis_inputs=None,
            live_cv=None,
        )
        assert counts["errors"] == 1


class TestRefreshAllBoards:
    async def test_one_dead_board_does_not_abort_others(self, gap_service, monkeypatch):
        from services.portfolio.gaps import ats

        def fake_fetcher_for(source):
            if source == "greenhouse":
                return _ok_fetch
            return _dead_fetch

        async def _ok_fetch(company_slug, *, client=None, if_none_match=None):
            return ats.FetchResult(
                postings=[
                    ats.RawPosting(
                        external_id="ok-1",
                        title="Eng",
                        jd_text="Kubernetes.",
                        url="https://x/ok-1",
                    )
                ],
                etag='"v1"',
            )

        async def _dead_fetch(company_slug, *, client=None, if_none_match=None):
            raise ats.FetchError("board is down")

        monkeypatch.setattr(
            "services.portfolio.gaps.gap_service.fetcher_for", fake_fetcher_for
        )

        results = await gap_service.refresh_all_boards(
            [("greenhouse", "acme4"), ("lever", "dead-board")],
            analysis_inputs=None,
            live_cv=None,
        )
        assert results["greenhouse/acme4"]["new"] == 1
        assert results["lever/dead-board"]["errors"] == 1
