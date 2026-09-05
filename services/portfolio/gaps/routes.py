"""Gap-analysis endpoints.

Kept in the `gaps/` package rather than the shared `routes.py`: this is a
self-contained feature with its own service, and `routes.py` is already the
CV-rendering surface.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from services.portfolio.constants import API_V1_PREFIX
from services.portfolio.dependencies import (
    get_document_service,
    get_gap_service,
    get_pdf_service,
)
from services.portfolio.documents.document_row import (
    KIND_CV,
    KIND_JD_VOCABULARY,
    KIND_SKILL_BANK,
)
from services.portfolio.documents.document_service import (
    DocumentService,
    document_sources,
)
from services.portfolio.gaps.gap_service import ANALYZER_VERSION, GapService
from services.portfolio.jd_input import PayloadTooLargeError, parse_jd_input
from services.portfolio.matching.baseline import BaselineError, parse_baseline
from services.portfolio.matching.gap import parse_vocabulary
from services.portfolio.pdf_generator import PdfService
from services.portfolio.schemas.gaps import (
    GapReportOut,
    LearningRoadmap,
    PostingCreated,
    PostingList,
)
from services.portfolio.settings import settings


logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}/gaps", tags=["gaps"])

get_gap_service_dep = Depends(get_gap_service)
get_pdf_service_dep = Depends(get_pdf_service)
get_document_service_dep = Depends(get_document_service)


async def _analysis_inputs(
    documents: DocumentService,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Load the bank, deferred pool and vocabulary, or fail loudly.

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
    try:
        if bank_payload is None or vocab_payload is None:
            raise BaselineError("skill bank or JD vocabulary is unavailable")
        bank = parse_baseline(bank_payload, "skills")
        deferred = parse_baseline(bank_payload, "deferred")
        vocabulary = parse_vocabulary(vocab_payload)
    except BaselineError as exc:
        logger.warning("Gap analysis inputs unavailable: %s", exc)
        raise HTTPException(
            status_code=500, detail="Gap analysis is unavailable"
        ) from None
    return bank, deferred, vocabulary


@router.post("", response_model=PostingCreated, status_code=201)
async def store_job_posting(
    request: Request,
    gap_service: GapService = get_gap_service_dep,
) -> PostingCreated:
    """Store a job posting for later analysis.

    Accepts the same formats as `/api/v1/cv/tailor` (JSON, PDF, DOCX, text,
    Markdown) via the shared `parse_jd_input`. Re-posting identical text
    returns the existing posting with `duplicate: true`.
    """
    try:
        jd = parse_jd_input(
            await request.body(),
            request.headers.get("content-type", ""),
            title=request.query_params.get("title", ""),
        )
    except PayloadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not jd.jd_text:
        raise HTTPException(status_code=422, detail="jd_text is required")

    posting, duplicate = await gap_service.store_posting(
        jd_text=jd.jd_text,
        title=jd.title,
        company=request.query_params.get("company", ""),
        url=request.query_params.get("url", ""),
    )
    if posting is None:
        raise HTTPException(status_code=503, detail="Could not store the job posting")
    return PostingCreated(
        id=posting.id, content_hash=posting.content_hash, duplicate=duplicate
    )


@router.get("/postings", response_model=PostingList)
async def list_job_postings(
    gap_service: GapService = get_gap_service_dep,
) -> PostingList:
    """List stored postings, newest first."""
    return PostingList(postings=await gap_service.list_postings())


@router.post("/postings/{posting_id}/analyze", response_model=GapReportOut)
async def analyze_job_posting(
    posting_id: int,
    gap_service: GapService = get_gap_service_dep,
    pdf_service: PdfService = get_pdf_service_dep,
    documents: DocumentService = get_document_service_dep,
) -> GapReportOut:
    """Analyse a stored posting and persist the gap report.

    Idempotent: re-analyzing at the same analyzer version overwrites the
    previous result rather than accumulating rows.
    """
    bank, deferred, vocabulary = await _analysis_inputs(documents)
    live_cv = await documents.read(
        KIND_CV, fallback_path=document_sources(settings).get(KIND_CV)
    )
    report = await gap_service.analyze_posting(
        posting_id,
        bank_atoms=bank,
        deferred_atoms=deferred,
        vocabulary=vocabulary,
        live_cv=live_cv if live_cv is not None else pdf_service.cv_data,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Job posting not found")
    return GapReportOut(
        posting_id=posting_id,
        coverage=report.coverage,
        gaps=[gap.__dict__ for gap in report.gaps],
    )


@router.get("/postings/{posting_id}", response_model=GapReportOut)
async def read_gap_report(
    posting_id: int,
    gap_service: GapService = get_gap_service_dep,
) -> GapReportOut:
    """Read a stored gap report."""
    report = await gap_service.get_analysis(posting_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No analysis for this posting")
    return GapReportOut(
        posting_id=posting_id,
        coverage=report.coverage,
        gaps=[gap.__dict__ for gap in report.gaps],
    )


@router.get("/roadmap", response_model=LearningRoadmap)
async def read_learning_roadmap(
    gap_service: GapService = get_gap_service_dep,
) -> LearningRoadmap:
    """Gap terms ranked by how many postings demand them.

    The first row is the answer to "what should I learn next?".
    """
    return LearningRoadmap(
        items=await gap_service.build_roadmap(), analyzer_version=ANALYZER_VERSION
    )
