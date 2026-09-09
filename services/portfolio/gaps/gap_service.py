"""Gap analysis application service.

Constructed once in the app's lifespan (`app.state.gap_service`), reached
by routes via `dependencies.get_gap_service`.

Degrade-don't-crash (mirrors `RevisionService`): a Postgres error logs a
warning and returns `None`/`[]` rather than raising. A transient DB hiccup
must never 500 the roadmap page.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from services.portfolio.documents.document_row import (
    KIND_JD_VOCABULARY,
    KIND_SKILL_BANK,
)
from services.portfolio.documents.document_service import document_sources
from services.portfolio.gaps.ats import TIMEOUT_SECONDS, USER_AGENT, fetcher_for
from services.portfolio.gaps.gap_repository import GapRepository
from services.portfolio.gaps.job_posting import (
    JobPosting,
    JobPostingSummary,
    PhraseCluster,
    RoadmapItem,
)
from services.portfolio.gaps.job_posting_document_store import (
    JobPostingDocument,
    JobPostingDocumentStore,
)
from services.portfolio.gaps.job_posting_row import JobPostingRow, PostingAnalysisRow
from services.portfolio.gaps.phrase_cluster_row import (
    PhraseClusterRow,
    PhraseEmbeddingRow,
)
from services.portfolio.matching.baseline import BaselineError, parse_baseline
from services.portfolio.matching.gap import GapReport, detect_gaps, parse_vocabulary
from services.portfolio.settings import settings


if TYPE_CHECKING:
    from services.portfolio.documents.document_service import DocumentService

# One shared client per refresh run: real User-Agent + a semaphore so a run
# never hits more than a couple of boards concurrently (politeness, not
# capacity — these are other people's ATS APIs).
_MAX_CONCURRENT_BOARDS = 2


logger = logging.getLogger(__name__)

# Bump when the vocabulary or extraction logic changes, so the roadmap never
# mixes extractor generations. Re-analysis: bump, re-run, query the new value.
ANALYZER_VERSION = "2"

# Tiers the roadmap ranks. "covered" is excluded: it is what the operator
# already has, and the page answers "what should I learn next?". "stale" IS
# ranked — a skill on the CV that needs refreshing is real work, and it is
# more urgent than an unknown one because a recruiter is already being shown
# it. Bumping ANALYZER_VERSION because the tier set changed.
ROADMAP_TIERS = ["stale", "unvouched", "deferred", "unknown"]

# Baked into the image at build time (see Dockerfile) — never downloaded at
# request time. Bump this alongside a model change so the embedding cache
# never mixes vectors from two model generations.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Starting point from eyeballing real JD sentences, not a derived constant.
# Expect to move it between 0.78-0.88 once real clusters are visible.
CLUSTER_THRESHOLD = 0.82


def content_hash(posting_text: str) -> str:
    """SHA-256 hex digest of the posting text, for dedup (not a secret)."""
    return hashlib.sha256(posting_text.encode("utf-8")).hexdigest()


class GapService:
    """Orchestrates posting storage and gap analysis.

    Depends on the `GapRepository` and `JobPostingDocumentStore` Protocols, not
    concrete implementations. `repo` (Postgres) holds the relational
    skeleton of a posting; `posting_docs` (Firestore) holds its raw text and
    per-portal metadata. The analysis itself is pure functions elsewhere;
    this service only handles persistence and the domain mapping.
    """

    def __init__(
        self, repo: GapRepository, posting_docs: JobPostingDocumentStore
    ) -> None:
        self._repo = repo
        self._posting_docs = posting_docs

    async def store_posting(
        self,
        *,
        posting_text: str,
        source: str = "manual",
        external_id: str | None = None,
        company: str = "",
        company_slug: str | None = None,
        title: str = "",
        url: str = "",
        raw_payload: dict[str, Any] | None = None,
    ) -> tuple[JobPosting | None, bool]:
        """Persist a posting, returning it and whether it already existed.

        Two distinct identities, two distinct dedup strategies:

        - No `external_id` (a pasted/manual posting): identity IS its text,
          so re-pasting the same text returns the existing row rather than a
          duplicate — the caller reports it as `duplicate: true`.
        - An `external_id` (ATS-sourced): identity is `(source, external_id)`
          per the portal, which stays stable even when a company edits its
          JD text. Content-hash dedup would wrongly treat an edited posting
          as brand new, so this path skips straight to `upsert_posting`'s
          `ON CONFLICT (source, external_id)`, which updates the existing
          row (and clears `closed_at`, "reopening" it) instead.

        `first_seen_at`/`last_seen_at` are set explicitly rather than left to
        the ORM `default=`: the session uses `expire_on_commit=False`, so the
        row is never reloaded after INSERT and a client-side default would
        leave `to_domain()` reading `None`.

        Consistency across the two stores (no shared transaction): the
        Firestore write happens *before* the Postgres write, deliberately.
        If Firestore fails, nothing is written to Postgres — no row can end
        up pointing at a missing document. If
        Firestore succeeds but the Postgres write then fails, the result is
        an orphaned Firestore document (unreachable, harmless, naturally
        overwritten by a future retry with the same text via `set()`'s
        idempotency) rather than an unreadable posting. The failure mode
        this ordering exists to prevent — `get_posting` returning a row
        whose `content_hash` has no Firestore document — is not eliminated
        (a process killed mid-write, or a manually deleted document, can
        still cause it), only made structurally impossible from this method.
        There is no reconciliation job for that residual case today.
        """
        digest = content_hash(posting_text)
        if external_id is None:
            try:
                existing = await self._repo.find_by_content_hash(digest)
            except Exception:
                logger.warning("Failed to check for duplicate posting", exc_info=True)
                existing = None
            if existing is not None:
                # Re-save rather than trust the row: the document may be gone
                # (killed mid-write, deleted out-of-band), and a row pointing
                # at a missing document 404s on analyze forever. `set()` is
                # idempotent and the text is identical by definition of the
                # hash match, so this is a no-op in the healthy case.
                try:
                    await self._posting_docs.save(
                        JobPostingDocument(
                            content_hash=digest,
                            posting_text=posting_text,
                            raw_payload=raw_payload or {},
                        )
                    )
                except Exception:
                    logger.warning(
                        "Failed to refresh document for existing posting %s",
                        existing.id,
                        exc_info=True,
                    )
                return existing.to_domain(posting_text=posting_text), True

        try:
            await self._posting_docs.save(
                JobPostingDocument(
                    content_hash=digest,
                    posting_text=posting_text,
                    raw_payload=raw_payload or {},
                )
            )
        except Exception:
            logger.warning("Failed to store posting document", exc_info=True)
            return None, False

        now = datetime.now(UTC)
        row = JobPostingRow(
            source=source,
            external_id=external_id,
            company=company,
            company_slug=company_slug,
            title=title,
            url=url,
            content_hash=digest,
            first_seen_at=now,
            last_seen_at=now,
        )
        try:
            stored = await self._repo.upsert_posting(posting=row)
        except Exception:
            logger.warning("Failed to persist job posting", exc_info=True)
            return None, False
        return stored.to_domain(posting_text=posting_text), False

    async def sync_ats_posting(
        self,
        *,
        source: str,
        external_id: str,
        company_slug: str,
        posting_text: str,
        company: str = "",
        title: str = "",
        url: str = "",
        raw_payload: dict[str, Any] | None = None,
    ) -> tuple[JobPosting | None, str]:
        """Sync one ATS-fetched posting, classifying what changed.

        Unlike `store_posting` (dedup for pasted text with no stable
        identity), an ATS posting's identity is `(source, external_id)` and
        stays fixed across edits — so this checks the *prior* row's
        content_hash first to tell the refresh job whether re-analysis is
        warranted, rather than treating every fetch as either brand-new or
        an exact duplicate.

        Returns `(posting, status)` where status is one of "new", "changed",
        "unchanged", or "error" (posting is `None` only on "error").
        """
        digest = content_hash(posting_text)
        try:
            existing = await self._repo.find_by_source_external_id(source, external_id)
        except Exception:
            logger.warning(
                "Failed to look up posting %s/%s", source, external_id, exc_info=True
            )
            existing = None

        if existing is not None and existing.content_hash == digest:
            status = "unchanged"
        elif existing is not None:
            status = "changed"
        else:
            status = "new"

        posting, _ = await self.store_posting(
            posting_text=posting_text,
            source=source,
            external_id=external_id,
            company=company,
            company_slug=company_slug,
            title=title,
            url=url,
            raw_payload=raw_payload,
        )
        if posting is None:
            return None, "error"
        return posting, status

    async def close_stale_board_postings(
        self, *, source: str, company_slug: str, seen_external_ids: set[str]
    ) -> int:
        """Close postings on one board absent from its current fetch.

        Call once per board after every posting from this fetch has been
        synced — never after a partial/failed fetch, or every posting on the
        board would be wrongly closed.
        """
        try:
            return await self._repo.close_missing_postings(
                source=source,
                company_slug=company_slug,
                seen_external_ids=seen_external_ids,
            )
        except Exception:
            logger.warning(
                "Failed to close missing postings for %s/%s",
                source,
                company_slug,
                exc_info=True,
            )
            return 0

    async def sync_board(
        self,
        *,
        source: str,
        company_slug: str,
        client: httpx.AsyncClient,
        analysis_inputs: tuple[
            list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
        ]
        | None,
        live_cv: dict[str, Any] | None,
    ) -> dict[str, int]:
        """Fetch one board, sync every posting, close what's gone, re-analyze changes.

        A dead board must never abort the whole refresh run, so every
        failure mode here degrades to a zero-count result rather than
        raising — `refresh_all_boards` relies on that to isolate boards from
        each other. `analysis_inputs`/`live_cv` are `None` when the caller
        couldn't load them (e.g. vocabulary unavailable); in that case
        postings still sync, they just aren't re-analyzed until the next run
        that has inputs.
        """
        counts = {"new": 0, "changed": 0, "unchanged": 0, "closed": 0, "errors": 0}
        fetcher = fetcher_for(source)
        if fetcher is None:
            logger.warning("No fetcher registered for ATS source %r", source)
            counts["errors"] += 1
            return counts

        try:
            board = await self._repo.get_board(source, company_slug)
        except Exception:
            logger.warning(
                "Failed to read board state for %s/%s",
                source,
                company_slug,
                exc_info=True,
            )
            board = None
        prior_etag = board.etag if board is not None else None

        try:
            result = await fetcher(
                company_slug, client=client, if_none_match=prior_etag
            )
        except Exception:
            logger.warning(
                "Fetch failed for %s/%s", source, company_slug, exc_info=True
            )
            counts["errors"] += 1
            return counts

        try:
            await self._repo.upsert_board(
                source=source, company_slug=company_slug, etag=result.etag
            )
        except Exception:
            logger.warning(
                "Failed to record board fetch for %s/%s",
                source,
                company_slug,
                exc_info=True,
            )

        if result.postings is None:
            # 304 Not Modified — the board's listing hasn't changed at all,
            # so there is nothing to sync or close this run.
            return counts

        seen_external_ids: set[str] = set()
        for raw in result.postings:
            seen_external_ids.add(raw.external_id)
            posting, status = await self.sync_ats_posting(
                source=source,
                external_id=raw.external_id,
                company_slug=company_slug,
                posting_text=raw.posting_text,
                title=raw.title,
                url=raw.url,
                raw_payload=raw.raw_payload,
            )
            if status == "error" or posting is None:
                counts["errors"] += 1
                continue
            counts[status] += 1
            if status in ("new", "changed") and analysis_inputs is not None:
                bank, deferred, vocabulary = analysis_inputs
                await self.analyze_posting(
                    posting.id,
                    bank_atoms=bank,
                    deferred_atoms=deferred,
                    vocabulary=vocabulary,
                    live_cv=live_cv or {},
                )

        closed = await self.close_stale_board_postings(
            source=source,
            company_slug=company_slug,
            seen_external_ids=seen_external_ids,
        )
        counts["closed"] = closed
        return counts

    async def refresh_all_boards(
        self,
        boards: list[tuple[str, str]],
        *,
        analysis_inputs: tuple[
            list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
        ]
        | None,
        live_cv: dict[str, Any] | None,
    ) -> dict[str, dict[str, int]]:
        """Sync every tracked board, a few at a time, isolating failures per board.

        `boards` is `[(source, company_slug), ...]` — the operator-configured
        list of what to poll. Returns per-board counts keyed by
        `"{source}/{company_slug}"`, so a caller (the refresh trigger's
        response body) can see exactly what happened without re-querying.
        """
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_BOARDS)
        results: dict[str, dict[str, int]] = {}

        async def _run(source: str, company_slug: str) -> None:
            async with semaphore:
                key = f"{source}/{company_slug}"
                try:
                    results[key] = await self.sync_board(
                        source=source,
                        company_slug=company_slug,
                        client=client,
                        analysis_inputs=analysis_inputs,
                        live_cv=live_cv,
                    )
                except Exception:
                    logger.warning("Board sync crashed for %s", key, exc_info=True)
                    results[key] = {"errors": 1}

        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        ) as client:
            await asyncio.gather(*(_run(source, slug) for source, slug in boards))
        return results

    async def get_posting(self, posting_id: int) -> JobPosting | None:
        """Read a posting, hydrating its text from the document store.

        The single seam every caller (analyze/cluster/route handlers) goes
        through — none of them need to know the text lives in Firestore, not
        the row they just fetched.
        """
        try:
            row = await self._repo.get_posting(posting_id)
        except Exception:
            logger.warning("Failed to read posting %s", posting_id, exc_info=True)
            return None
        if row is None:
            return None

        try:
            document = await self._posting_docs.get(row.content_hash)
        except Exception:
            logger.warning(
                "Failed to read posting document for posting %s",
                posting_id,
                exc_info=True,
            )
            return None
        if document is None:
            logger.warning(
                "Posting %s has no document for content_hash %s",
                posting_id,
                row.content_hash,
            )
            return None
        return row.to_domain(posting_text=document.posting_text)

    async def list_postings(
        self, *, mentions_term: str | None = None
    ) -> list[JobPostingSummary]:
        """List postings, optionally filtered to ones whose analysis mentions a term.

        `mentions_term` matches on any tier — "the JD asked for this",
        regardless of how confidently the CV covers it. Always filters
        against the *current* `ANALYZER_VERSION`; a posting analyzed only
        under an older generation won't match until it's re-analyzed.
        """
        try:
            rows = await self._repo.list_postings(
                mentions_term=mentions_term, analyzer_version=ANALYZER_VERSION
            )
        except Exception:
            logger.warning("Failed to list postings", exc_info=True)
            return []
        return [JobPostingSummary.model_validate(row) for row in rows]

    async def analyze_posting(
        self,
        posting_id: int,
        *,
        bank_atoms: list[dict[str, Any]],
        deferred_atoms: list[dict[str, Any]],
        vocabulary: list[dict[str, Any]],
        live_cv: dict[str, Any],
    ) -> GapReport | None:
        """Analyse a stored posting and persist the result.

        Returns None when the posting is missing or a DB error occurs. The
        write is an upsert on (posting_id, analyzer_version), so re-analyzing
        is idempotent.
        """
        posting = await self.get_posting(posting_id)
        if posting is None:
            return None

        report = detect_gaps(
            posting.posting_text, bank_atoms, deferred_atoms, vocabulary, live_cv
        )
        row = PostingAnalysisRow(
            posting_id=posting_id,
            analyzer_version=ANALYZER_VERSION,
            result={"gaps": [asdict(gap) for gap in report.gaps]},
            created_at=datetime.now(UTC),
        )
        try:
            await self._repo.save_analysis(analysis=row)
        except Exception:
            logger.warning(
                "Failed to persist analysis for posting %s", posting_id, exc_info=True
            )
            return None
        return report

    async def get_analysis(self, posting_id: int) -> GapReport | None:
        """Read a stored analysis at the current analyzer version."""
        try:
            row = await self._repo.get_analysis(posting_id, ANALYZER_VERSION)
        except Exception:
            logger.warning("Failed to read analysis %s", posting_id, exc_info=True)
            return None
        if row is None:
            return None
        return _report_from_result(row.result)

    async def build_roadmap(self) -> list[RoadmapItem]:
        """Rank gap terms by how many postings demand them.

        `posting_count` descending is the product: the first row is what to learn
        next.
        """
        try:
            rows = await self._repo.aggregate_roadmap(
                analyzer_version=ANALYZER_VERSION, tiers=ROADMAP_TIERS
            )
        except Exception:
            logger.warning("Failed to aggregate roadmap", exc_info=True)
            return []
        return [RoadmapItem(**row) for row in rows]

    async def cluster_posting(
        self, posting_id: int, *, threshold: float = CLUSTER_THRESHOLD
    ) -> list[PhraseCluster] | None:
        """Group this posting's paraphrased responsibility sentences.

        Returns None when the posting is missing, embedding fails, or a DB
        error occurs. Embeddings are cached by phrase content hash *and*
        `EMBEDDING_MODEL` — a model bump treats every prior row as a cache
        miss rather than mixing vectors from two model generations in one
        clustering run. Re-clustering a posting replaces its prior result;
        a posting with no clusterable phrases persists an empty result too,
        so a later read sees `[]` rather than 404ing on unanalyzed state.
        """
        from services.portfolio.matching.clustering import (
            cluster_vectors,
            embed_phrases,
            medoid_index,
            segment_phrases,
        )

        posting = await self.get_posting(posting_id)
        if posting is None:
            return None

        phrases = segment_phrases(posting.posting_text)
        if not phrases:
            return await self._save_clusters(posting_id, [], threshold)

        hashes = [content_hash(phrase) for phrase in phrases]
        try:
            cached = await self._repo.get_cached_embeddings(
                hashes, model_name=EMBEDDING_MODEL
            )
        except Exception:
            logger.warning(
                "Failed to read cached embeddings for posting %s",
                posting_id,
                exc_info=True,
            )
            return None

        missing = [
            (phrase, digest)
            for phrase, digest in zip(phrases, hashes, strict=True)
            if digest not in cached
        ]
        if missing:
            try:
                # embed_phrases runs real model inference (CPU-bound, via
                # fastembed/onnxruntime) — offloaded to a worker thread so it
                # never blocks the event loop for other in-flight requests.
                new_vectors = await asyncio.to_thread(
                    embed_phrases, [phrase for phrase, _ in missing]
                )
                if len(new_vectors) != len(missing):
                    raise ValueError(
                        f"embed_phrases returned {len(new_vectors)} vectors "
                        f"for {len(missing)} phrases"
                    )
            except Exception:
                logger.warning(
                    "Failed to embed phrases for posting %s", posting_id, exc_info=True
                )
                return None

            new_rows = [
                PhraseEmbeddingRow(
                    content_hash=digest,
                    phrase=phrase,
                    vector=vector,
                    model_name=EMBEDDING_MODEL,
                    created_at=datetime.now(UTC),
                )
                for (phrase, digest), vector in zip(missing, new_vectors, strict=True)
            ]
            try:
                await self._repo.save_embeddings(rows=new_rows)
            except Exception:
                logger.warning(
                    "Failed to cache embeddings for posting %s",
                    posting_id,
                    exc_info=True,
                )
            for (_, digest), vector in zip(missing, new_vectors, strict=True):
                cached[digest] = vector

        vectors = [cached[digest] for digest in hashes]
        groups = cluster_vectors(vectors, threshold=threshold)
        clusters = [
            PhraseCluster(
                label=phrases[medoid_index(vectors, group)],
                phrases=[phrases[i] for i in group],
            )
            for group in groups
        ]
        return await self._save_clusters(posting_id, clusters, threshold)

    async def _save_clusters(
        self, posting_id: int, clusters: list[PhraseCluster], threshold: float
    ) -> list[PhraseCluster] | None:
        """Persist a clustering result (possibly empty) and return it, or
        None on a DB error."""
        row = PhraseClusterRow(
            posting_id=posting_id,
            clusters=[cluster.model_dump() for cluster in clusters],
            threshold=threshold,
            created_at=datetime.now(UTC),
        )
        try:
            await self._repo.save_phrase_clusters(row=row)
        except Exception:
            logger.warning(
                "Failed to persist clusters for posting %s", posting_id, exc_info=True
            )
            return None
        return clusters

    async def get_phrase_clusters(self, posting_id: int) -> list[PhraseCluster] | None:
        """Read a posting's stored clustering result."""
        try:
            row = await self._repo.get_phrase_clusters(posting_id)
        except Exception:
            logger.warning(
                "Failed to read clusters for posting %s", posting_id, exc_info=True
            )
            return None
        if row is None:
            return None
        return [PhraseCluster(**cluster) for cluster in row.clusters]


def _report_from_result(result: dict[str, Any]) -> GapReport:
    """Rebuild a GapReport from its stored JSONB form."""
    from services.portfolio.matching.gap import SkillGap

    return GapReport(gaps=tuple(SkillGap(**gap) for gap in result.get("gaps", [])))


async def load_analysis_inputs(
    documents: DocumentService,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load the bank, deferred pool and vocabulary, or fail loudly.

    Framework-free: raises `BaselineError` rather than an HTTP exception, so
    both the FastAPI route and the standalone refresh trigger process (no
    FastAPI request in scope) can call this and translate the failure their
    own way.

    Reads through `DocumentService`, so an operator edit made via
    `PUT /api/v1/documents/{kind}` takes effect immediately, and a database
    miss falls back to the shipped JSON files.

    A missing vocabulary would silently sink every term into the "unknown"
    tier, so this raises rather than degrading — a wrong roadmap is worse
    than an error.
    """
    sources = document_sources(settings)
    bank_payload = await documents.read(
        KIND_SKILL_BANK, fallback_path=sources[KIND_SKILL_BANK]
    )
    vocab_payload = await documents.read(
        KIND_JD_VOCABULARY, fallback_path=sources[KIND_JD_VOCABULARY]
    )
    if bank_payload is None or vocab_payload is None:
        raise BaselineError("skill bank or JD vocabulary is unavailable")
    bank = parse_baseline(bank_payload, "skills")
    deferred = parse_baseline(bank_payload, "deferred")
    vocabulary = parse_vocabulary(vocab_payload)
    return bank, deferred, vocabulary
