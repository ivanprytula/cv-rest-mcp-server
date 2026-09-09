"""Job-posting document store — port (Protocol) + Firestore adapter + in-memory fake.

Raw posting text and per-portal metadata live here, not in Postgres. At the
scale this is heading toward (many ATSs and job boards, tens of thousands of
companies), duplicating that payload into both stores would mean two writes
with no shared transaction per posting, and maintaining the same per-portal
schema heterogeneity twice. Postgres keeps only the relational skeleton —
ids, hashes, timestamps — and this store keeps the (heterogeneous,
schemaless) raw document, keyed by content hash so the existing
dedup-by-hash logic doubles as the document key.

No FK, no cross-store transaction, so integrity here is ordering, not
atomicity: every write path (`GapService.store_posting`) writes the
Firestore document *before* the Postgres row, so a Postgres row can never
legitimately exist pointing at a missing document — a failed Firestore
write aborts before Postgres is touched at all. A row can still lose its
document afterwards (process killed between the two writes, or a document
deleted out-of-band); re-storing the same text repairs it, because the
dedup path re-saves the document instead of trusting the existing row, and
`GapService.get_posting` treats a still-missing document as a
warning-logged failure (returns `None`), never a crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class JobPostingDocument:
    """One raw JD's text and portal metadata, however it arrived."""

    content_hash: str
    posting_text: str
    raw_payload: dict[str, Any] = field(default_factory=dict)


class JobPostingDocumentStore(Protocol):
    async def save(self, document: JobPostingDocument) -> None: ...
    async def get(self, content_hash: str) -> JobPostingDocument | None: ...


class FirestoreJobPostingDocumentStore:
    """Firestore-backed store. Collection: `job_posting_documents/{content_hash}`.

    Uses the async client so a slow Firestore call never blocks the event
    loop the way a sync client would.
    """

    def __init__(self, client) -> None:
        self._client = client

    def _doc_ref(self, content_hash: str):
        return self._client.collection("job_posting_documents").document(content_hash)

    async def save(self, document: JobPostingDocument) -> None:
        await self._doc_ref(document.content_hash).set(
            {"posting_text": document.posting_text, "raw_payload": document.raw_payload}
        )

    async def get(self, content_hash: str) -> JobPostingDocument | None:
        snapshot = await self._doc_ref(content_hash).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        return JobPostingDocument(
            content_hash=content_hash,
            posting_text=data.get("posting_text", ""),
            raw_payload=data.get("raw_payload", {}),
        )


class InMemoryJobPostingDocumentStore:
    """Hermetic fake behind the same Protocol — what most tests use.

    Keeps the suite fast and Docker-free; the real adapter is covered
    separately by the emulator-backed tests, which are opt-in.
    """

    def __init__(self) -> None:
        self._documents: dict[str, JobPostingDocument] = {}

    async def save(self, document: JobPostingDocument) -> None:
        self._documents[document.content_hash] = document

    async def get(self, content_hash: str) -> JobPostingDocument | None:
        return self._documents.get(content_hash)


def build_job_posting_document_store_from_settings() -> JobPostingDocumentStore:
    """`FirestoreJobPostingDocumentStore` if a project is configured, else the fake.

    Empty setting means skip the real client — local dev with no
    `FIRESTORE_PROJECT` set runs entirely in-memory, no GCP credentials
    required.
    """
    from services.portfolio.settings import settings

    if not settings.firestore_project:
        return InMemoryJobPostingDocumentStore()

    from google.cloud.firestore import AsyncClient

    return FirestoreJobPostingDocumentStore(
        AsyncClient(project=settings.firestore_project)
    )
