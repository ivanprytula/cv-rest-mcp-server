"""ATS board fetchers — Greenhouse, Lever, and Ashby JSON APIs.

Each portal hosts many companies' boards, so a "board" is identified by
`(source, company_slug)`, not by portal name alone. Every fetcher returns a
`FetchResult` of `RawPosting`, normalized to the same shape regardless of
portal — `gap_service.sync_ats_posting()` doesn't need to know which portal a
posting came from. Passing the board's stored `etag` back in as
`if_none_match` lets a fetcher return `postings=None` on a `304`, so the
caller can skip re-parsing (and re-syncing) an unchanged board entirely.

Politeness: one shared `httpx.AsyncClient`, a real User-Agent naming the
project (some portals block the default httpx UA), and a semaphore so a
refresh run never hits more than a couple of boards concurrently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import httpx

from services.portfolio.matching.normalize import normalize_jd_text


logger = logging.getLogger(__name__)

USER_AGENT = "cv-rest-mcp-server-ats-fetcher/1.0 (+https://github.com/ivanprytula/cv-rest-mcp-server)"
TIMEOUT_SECONDS = 15


@dataclass
class RawPosting:
    """One posting as fetched from a portal, normalized to a common shape."""

    external_id: str
    title: str
    jd_text: str
    url: str
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """One board fetch: either a fresh listing, or "unchanged" via ETag.

    `postings is None` means the portal returned `304 Not Modified` — the
    caller should skip this board entirely rather than re-parse anything.
    `etag` is the value to send as `If-None-Match` on the *next* fetch
    (`None` if the portal didn't send one, e.g. after a real error was
    avoided by falling through with no conditional match).
    """

    postings: list[RawPosting] | None
    etag: str | None


class FetchError(Exception):
    """Raised when a board's response can't be parsed as postings.

    Caught per-board by the sync loop — one dead board must never abort a
    refresh run for every other tracked board.
    """


class _HtmlTextExtractor(HTMLParser):
    """Strip tags from portal-supplied HTML, keeping block-level line breaks.

    Stdlib-only: ATS `content` fields are simple formatted text (`<p>`,
    `<li>`, `<strong>`, ...), not documents needing real HTML semantics, so
    `html.parser` is enough — no reason to add a dependency for it.
    """

    _BLOCK_TAGS = frozenset(
        {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "ul", "ol"}
    )

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _html_to_text(html: str) -> str:
    extractor = _HtmlTextExtractor()
    extractor.feed(html)
    return extractor.text()


def _client(client: httpx.AsyncClient | None) -> httpx.AsyncClient:
    return client or httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
    )


def _conditional_headers(if_none_match: str | None) -> dict[str, str]:
    return {"If-None-Match": if_none_match} if if_none_match else {}


async def fetch_greenhouse(
    company_slug: str,
    *,
    client: httpx.AsyncClient | None = None,
    if_none_match: str | None = None,
) -> FetchResult:
    """Fetch open postings from a Greenhouse job board.

    API: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    owns_client = client is None
    http = _client(client)
    try:
        response = await http.get(
            url,
            params={"content": "true"},
            headers=_conditional_headers(if_none_match),
        )
        if response.status_code == 304:
            return FetchResult(postings=None, etag=if_none_match)
        response.raise_for_status()
        payload = response.json()
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            raise FetchError(
                f"Greenhouse board {company_slug!r}: unexpected payload shape"
            )
        postings = [
            RawPosting(
                external_id=str(job["id"]),
                title=job.get("title", ""),
                jd_text=normalize_jd_text(_html_to_text(job.get("content", ""))),
                url=job.get("absolute_url", ""),
                raw_payload=job,
            )
            for job in jobs
        ]
        return FetchResult(postings=postings, etag=response.headers.get("etag"))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise FetchError(f"Greenhouse board {company_slug!r}: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()


async def fetch_lever(
    company_slug: str,
    *,
    client: httpx.AsyncClient | None = None,
    if_none_match: str | None = None,
) -> FetchResult:
    """Fetch open postings from a Lever job board.

    API: https://api.lever.co/v0/postings/{slug}?mode=json
    """
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    owns_client = client is None
    http = _client(client)
    try:
        response = await http.get(
            url,
            params={"mode": "json"},
            headers=_conditional_headers(if_none_match),
        )
        if response.status_code == 304:
            return FetchResult(postings=None, etag=if_none_match)
        response.raise_for_status()
        postings = response.json()
        if not isinstance(postings, list):
            raise FetchError(f"Lever board {company_slug!r}: unexpected payload shape")
        results = []
        for posting in postings:
            description_parts = [
                posting.get("descriptionPlain", "")
                or _html_to_text(posting.get("description", "")),
                *(
                    _html_to_text(section.get("content", ""))
                    for section in posting.get("lists", [])
                ),
            ]
            results.append(
                RawPosting(
                    external_id=str(posting["id"]),
                    title=posting.get("text", ""),
                    jd_text=normalize_jd_text(
                        "\n\n".join(p for p in description_parts if p)
                    ),
                    url=posting.get("hostedUrl", ""),
                    raw_payload=posting,
                )
            )
        return FetchResult(postings=results, etag=response.headers.get("etag"))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise FetchError(f"Lever board {company_slug!r}: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()


async def fetch_ashby(
    company_slug: str,
    *,
    client: httpx.AsyncClient | None = None,
    if_none_match: str | None = None,
) -> FetchResult:
    """Fetch open postings from an Ashby job board.

    API: https://api.ashbyhq.com/posting-api/job-board/{slug}
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
    owns_client = client is None
    http = _client(client)
    try:
        response = await http.get(url, headers=_conditional_headers(if_none_match))
        if response.status_code == 304:
            return FetchResult(postings=None, etag=if_none_match)
        response.raise_for_status()
        payload = response.json()
        jobs = payload.get("jobs", [])
        if not isinstance(jobs, list):
            raise FetchError(f"Ashby board {company_slug!r}: unexpected payload shape")
        postings = [
            RawPosting(
                external_id=str(job["id"]),
                title=job.get("title", ""),
                jd_text=normalize_jd_text(
                    job.get("descriptionPlain")
                    or _html_to_text(job.get("descriptionHtml", ""))
                ),
                url=job.get("jobUrl", ""),
                raw_payload=job,
            )
            for job in jobs
        ]
        return FetchResult(postings=postings, etag=response.headers.get("etag"))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise FetchError(f"Ashby board {company_slug!r}: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()


_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


def fetcher_for(source: str):
    """Return the fetch function for a portal name, or None if unknown."""
    return _FETCHERS.get(source)


def parse_tracked_boards(raw: str) -> list[tuple[str, str]]:
    """Parse "source:company_slug" pairs, comma-separated, from settings.

    Fails fast on a malformed entry (missing colon, unknown portal) so
    misconfiguration surfaces at startup rather than as a silent skip
    during a scheduled refresh.
    """
    boards: list[tuple[str, str]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                f"Invalid ATS board entry {entry!r}: expected 'source:company_slug'"
            )
        source, _, company_slug = entry.partition(":")
        if fetcher_for(source) is None:
            raise ValueError(f"Unknown ATS source {source!r} in {entry!r}")
        boards.append((source, company_slug))
    return boards
