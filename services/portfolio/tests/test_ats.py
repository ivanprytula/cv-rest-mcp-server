"""Tests for ATS board fetchers — recorded JSON fixtures, never live HTTP."""

import httpx
import pytest

from services.portfolio.gaps.ats import (
    FetchError,
    fetch_ashby,
    fetch_greenhouse,
    fetch_lever,
    fetcher_for,
)


def _client_returning(json_body, status_code=200, headers=None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body, headers=headers or {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client_returning_304() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("if-none-match") == '"abc"'
        return httpx.Response(304)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestFetchGreenhouse:
    async def test_parses_jobs_and_strips_html(self):
        client = _client_returning(
            {
                "jobs": [
                    {
                        "id": 12345,
                        "title": "Backend Engineer",
                        "content": "<p>We use <strong>Kubernetes</strong>.</p>",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/12345",
                    }
                ]
            },
            headers={"etag": '"gh-etag"'},
        )
        result = await fetch_greenhouse("acme", client=client)
        assert result.postings is not None
        (posting,) = result.postings
        assert posting.external_id == "12345"
        assert posting.title == "Backend Engineer"
        assert "Kubernetes" in posting.jd_text
        assert "<p>" not in posting.jd_text
        assert posting.url.endswith("/12345")
        assert result.etag == '"gh-etag"'

    async def test_http_error_raises_fetch_error(self):
        client = _client_returning({}, status_code=500)
        with pytest.raises(FetchError):
            await fetch_greenhouse("acme", client=client)

    async def test_malformed_payload_raises_fetch_error(self):
        client = _client_returning({"jobs": "not-a-list"})
        with pytest.raises(FetchError):
            await fetch_greenhouse("acme", client=client)

    async def test_304_returns_none_postings_and_sends_if_none_match(self):
        client = _client_returning_304()
        result = await fetch_greenhouse("acme", client=client, if_none_match='"abc"')
        assert result.postings is None
        assert result.etag == '"abc"'


class TestFetchLever:
    async def test_parses_postings_and_joins_sections(self):
        client = _client_returning(
            [
                {
                    "id": "abc-123",
                    "text": "Platform Engineer",
                    "descriptionPlain": "We run on Postgres.",
                    "lists": [{"content": "<li>Terraform</li>"}],
                    "hostedUrl": "https://jobs.lever.co/acme/abc-123",
                }
            ]
        )
        result = await fetch_lever("acme", client=client)
        assert result.postings is not None
        (posting,) = result.postings
        assert posting.external_id == "abc-123"
        assert "Postgres" in posting.jd_text
        assert "Terraform" in posting.jd_text

    async def test_http_error_raises_fetch_error(self):
        client = _client_returning([], status_code=404)
        with pytest.raises(FetchError):
            await fetch_lever("acme", client=client)

    async def test_304_returns_none_postings(self):
        client = _client_returning_304()
        result = await fetch_lever("acme", client=client, if_none_match='"abc"')
        assert result.postings is None


class TestFetchAshby:
    async def test_parses_jobs_with_plain_description(self):
        client = _client_returning(
            {
                "jobs": [
                    {
                        "id": "xyz-789",
                        "title": "SRE",
                        "descriptionPlain": "GraphQL and Kafka experience wanted.",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/xyz-789",
                    }
                ]
            }
        )
        result = await fetch_ashby("acme", client=client)
        assert result.postings is not None
        (posting,) = result.postings
        assert posting.external_id == "xyz-789"
        assert "Kafka" in posting.jd_text

    async def test_falls_back_to_html_description(self):
        client = _client_returning(
            {
                "jobs": [
                    {
                        "id": "xyz-790",
                        "title": "SRE",
                        "descriptionHtml": "<p>Redis required.</p>",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/xyz-790",
                    }
                ]
            }
        )
        result = await fetch_ashby("acme", client=client)
        assert result.postings is not None
        (posting,) = result.postings
        assert "Redis" in posting.jd_text
        assert "<p>" not in posting.jd_text

    async def test_304_returns_none_postings(self):
        client = _client_returning_304()
        result = await fetch_ashby("acme", client=client, if_none_match='"abc"')
        assert result.postings is None


class TestFetcherFor:
    def test_known_portals_resolve(self):
        assert fetcher_for("greenhouse") is fetch_greenhouse
        assert fetcher_for("lever") is fetch_lever
        assert fetcher_for("ashby") is fetch_ashby

    def test_unknown_portal_returns_none(self):
        assert fetcher_for("workday") is None


class TestParseTrackedBoards:
    def test_parses_comma_separated_pairs(self):
        from services.portfolio.gaps.ats import parse_tracked_boards

        assert parse_tracked_boards("greenhouse:stripe,lever:netflix") == [
            ("greenhouse", "stripe"),
            ("lever", "netflix"),
        ]

    def test_empty_string_yields_no_boards(self):
        from services.portfolio.gaps.ats import parse_tracked_boards

        assert parse_tracked_boards("") == []

    def test_missing_colon_raises(self):
        from services.portfolio.gaps.ats import parse_tracked_boards

        with pytest.raises(ValueError, match="expected"):
            parse_tracked_boards("greenhouse-stripe")

    def test_unknown_source_raises(self):
        from services.portfolio.gaps.ats import parse_tracked_boards

        with pytest.raises(ValueError, match="Unknown ATS source"):
            parse_tracked_boards("workday:acme")
