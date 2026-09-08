"""JD document store — port (Protocol) + Firestore adapter + in-memory fake.

Raw job-description text and per-portal metadata live here, not in Postgres.
At the scale this is heading toward (many ATSs and job boards, tens of
thousands of companies), duplicating that payload into both stores would mean
two writes with no shared transaction per posting, and maintaining the same
per-portal schema heterogeneity twice. Postgres (`job_posting_row.py`) keeps
only the relational skeleton — ids, hashes, timestamps — and this store keeps
the (heterogeneous, schemaless) raw document, keyed by content hash so the
existing dedup-by-hash logic in `gap_service.py` doubles as the document key.

No FK, no cross-store transaction, so integrity here is ordering, not
atomicity: every write path (`GapService.store_posting`) writes the
Firestore document *before* the Postgres row, so a Postgres row can never
legitimately exist pointing at a missing document — a failed Firestore
write aborts before Postgres is touched at all. The residual risk this
does NOT close is a process killed between the two writes, or a document
deleted out-of-band after the fact; there is no reconciliation job for
that today, matching the tradeoff the original Phase 2b plan accepted for
this design. `GapService.get_posting` treats a missing document as a
warning-logged failure (returns `None`), never a crash, so that residual
case degrades to "posting temporarily unreadable," not silent corruption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class JdDocument:
    """One raw JD's text and portal metadata, however it arrived."""

    content_hash: str
    jd_text: str
    raw_payload: dict[str, Any] = field(default_factory=dict)


class JdDocumentStore(Protocol):
    async def save(self, document: JdDocument) -> None: ...
    async def get(self, content_hash: str) -> JdDocument | None: ...


class FirestoreJdDocumentStore:
    """Firestore-backed store. Collection: `jd_documents/{content_hash}`.

    Uses the async client so a slow Firestore call never blocks the event
    loop the way a sync client would (see the same rationale FastAPI/asyncpg
    already follow elsewhere in this service).
    """

    def __init__(self, client) -> None:
        self._client = client

    def _doc_ref(self, content_hash: str):
        return self._client.collection("jd_documents").document(content_hash)

    async def save(self, document: JdDocument) -> None:
        await self._doc_ref(document.content_hash).set(
            {"jd_text": document.jd_text, "raw_payload": document.raw_payload}
        )

    async def get(self, content_hash: str) -> JdDocument | None:
        snapshot = await self._doc_ref(content_hash).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        return JdDocument(
            content_hash=content_hash,
            jd_text=data.get("jd_text", ""),
            raw_payload=data.get("raw_payload", {}),
        )


class InMemoryJdDocumentStore:
    """Hermetic fake behind the same Protocol — what tests use.

    The real Firestore adapter has no emulator in CI, so it stays untested;
    this fake is what `GapService`'s tests actually exercise, same pattern
    as every other repository fake in this codebase.
    """

    def __init__(self) -> None:
        self._documents: dict[str, JdDocument] = {}

    async def save(self, document: JdDocument) -> None:
        self._documents[document.content_hash] = document

    async def get(self, content_hash: str) -> JdDocument | None:
        return self._documents.get(content_hash)


def build_jd_document_store_from_settings() -> JdDocumentStore:
    """`FirestoreJdDocumentStore` if a project is configured, else the fake.

    Mirrors `cv_source.build_cv_source_from_settings`'s "empty setting means
    skip the real client" pattern — local dev with no `FIRESTORE_PROJECT` set
    runs entirely in-memory, no GCP credentials required.
    """
    from services.portfolio.settings import settings

    if not settings.firestore_project:
        return InMemoryJdDocumentStore()

    from google.cloud.firestore import AsyncClient

    return FirestoreJdDocumentStore(AsyncClient(project=settings.firestore_project))
