"""CRUD for a tenant's documents (live CV, skill bank, JD vocabulary).

Every route acts on the caller's own tenant, resolved from the access
token — there is no path parameter for whose documents to touch, so no
request can name another tenant's. Reads need `cv:read`, writes `cv:manage`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from services.portfolio.constants import API_V1_PREFIX
from services.portfolio.cv_data import validate_cv_payload
from services.portfolio.cv_extraction import (
    MAX_RESUME_TEXT_CHARS,
    CVExtractionError,
    CVExtractionService,
)
from services.portfolio.cv_review.critic_agent import CVCritiqueError
from services.portfolio.cv_review.review_service import CVReviewService
from services.portfolio.dependencies import (
    get_cv_extraction_service,
    get_cv_review_service,
    get_document_service,
    get_tenant_id,
)
from services.portfolio.documents.document_row import (
    DOCUMENT_KINDS,
    KIND_CV,
    KIND_JD_VOCABULARY,
    KIND_SKILL_BANK,
)
from services.portfolio.documents.document_service import (
    DocumentService,
    document_sources,
)
from services.portfolio.job_posting_input import (
    PayloadTooLargeError,
    parse_job_posting_input,
)
from services.portfolio.matching.baseline import BaselineError, validate_bank_payload
from services.portfolio.settings import settings
from services.portfolio.tenancy import TenantId


logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}/documents", tags=["documents"])

get_document_service_dep = Depends(get_document_service)
tenant_id_dep = Depends(get_tenant_id)
get_cv_extraction_service_dep = Depends(get_cv_extraction_service)
get_cv_review_service_dep = Depends(get_cv_review_service)

# Derived from DOCUMENT_KINDS, never duplicated: a hand-written pattern here
# would silently reject a kind added to that tuple.
kind_path = Path(
    description="Document kind",
    pattern=f"^({'|'.join(DOCUMENT_KINDS)})$",
)


# Per-kind validators. A kind absent here is stored as-is — adding a new
# document kind should not require inventing a schema for it, and an
# unvalidated document is only a risk to whatever chooses to read it.
_VALIDATORS = {
    KIND_CV: lambda payload: validate_cv_payload(payload),
    KIND_SKILL_BANK: lambda payload: validate_bank_payload(KIND_SKILL_BANK, payload),
    KIND_JD_VOCABULARY: lambda payload: validate_bank_payload(
        KIND_JD_VOCABULARY, payload
    ),
}


def _validate(kind: str, payload: dict[str, Any]) -> None:
    """Reject a document that would break the feature reading it.

    Validation happens on write, not on read: a bad document stored is a
    bad document served to every later request.
    """
    validator = _VALIDATORS.get(kind)
    if validator is None:
        return
    try:
        validator(payload)
    except (ValueError, BaselineError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("")
async def list_documents(
    service: DocumentService = get_document_service_dep,
    tenant_id: TenantId = tenant_id_dep,
) -> dict[str, Any]:
    """Report which of this tenant's documents are stored, and at which version.

    A kind absent here is being served from its file fallback.
    """
    return {
        "kinds": list(DOCUMENT_KINDS),
        "versions": await service.versions(tenant_id=tenant_id),
    }


@router.get("/{kind}")
async def read_document(
    kind: str = kind_path,
    service: DocumentService = get_document_service_dep,
    tenant_id: TenantId = tenant_id_dep,
) -> dict[str, Any]:
    """Read this tenant's document — from the DB, or its file fallback."""
    payload = await service.read(
        kind,
        tenant_id=tenant_id,
        fallback_path=document_sources(settings).get(kind),
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No {kind} document available")
    return payload


@router.put("/{kind}")
async def write_document(
    payload: dict[str, Any],
    kind: str = kind_path,
    service: DocumentService = get_document_service_dep,
    tenant_id: TenantId = tenant_id_dep,
) -> dict[str, Any]:
    """Replace this tenant's document. Validated before storing."""
    _validate(kind, payload)
    version = await service.write(kind, payload, tenant_id=tenant_id)
    if version is None:
        raise HTTPException(
            status_code=503, detail=f"Could not store the {kind} document"
        )
    return {"kind": kind, "version": version}


_RAW_UPLOAD_REQUEST_BODY = {
    "content": {
        media_type: {"schema": {"type": "string", "format": "binary"}}
        for media_type in (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
            "text/markdown",
            "application/json",
        )
    }
}


async def _parsed_resume_text(request: Request) -> str:
    """Shared upload parsing for `/cv/extract` and `/cv/review`.

    Raises the same 413/422 `HTTPException`s either route would raise on
    its own — factored out because both need identical parsing, not
    because either alone would justify a helper.
    """
    try:
        parsed = parse_job_posting_input(
            await request.body(), request.headers.get("content-type", "")
        )
    except PayloadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not parsed.posting_text:
        raise HTTPException(status_code=422, detail="Uploaded file has no text")
    if len(parsed.posting_text) > MAX_RESUME_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Extracted text exceeds {MAX_RESUME_TEXT_CHARS:,} characters",
        )
    return parsed.posting_text


@router.post("/cv/extract", openapi_extra={"requestBody": _RAW_UPLOAD_REQUEST_BODY})
async def extract_cv_draft(
    request: Request,
    extraction: CVExtractionService = get_cv_extraction_service_dep,
) -> dict[str, Any]:
    """Draft a CV document from an uploaded resume file.

    Accepts the same formats as job-posting intake (JSON, PDF, DOCX, text,
    Markdown). Returns the extracted draft for review — it is never written
    to this tenant's document store here; the caller reviews/edits it and
    then PUTs `/documents/cv` themselves to save it. Requires no tenant_id
    of its own: `cv:manage` (checked by the middleware) is the whole gate,
    since nothing is persisted by this route.
    """
    resume_text = await _parsed_resume_text(request)
    try:
        draft = await extraction.extract(resume_text)
    except CVExtractionError as exc:
        # The raw message can carry upstream API internals (request/response
        # detail from anthropic.APIError) — logged, never returned to the
        # client, same as every other service-internal failure in this app.
        logger.warning("CV extraction failed: %s", exc)
        raise HTTPException(status_code=502, detail="CV extraction failed") from None
    return draft


@router.post("/cv/review", openapi_extra={"requestBody": _RAW_UPLOAD_REQUEST_BODY})
async def review_cv_draft(
    request: Request,
    review: CVReviewService = get_cv_review_service_dep,
) -> dict[str, Any]:
    """Draft a CV document, with a critique of the draft alongside it.

    Same upload/parsing/gate as `/cv/extract` — this is additive, not a
    replacement: `/cv/extract` still returns just the draft for a caller
    that doesn't want the extra model call. Nothing is persisted here
    either; the human reviews the draft (informed by the critique) before
    PUTting `/documents/cv` themselves.
    """
    resume_text = await _parsed_resume_text(request)
    try:
        result = await review.run(resume_text)
    except (CVExtractionError, CVCritiqueError) as exc:
        logger.warning("CV review failed: %s", exc)
        raise HTTPException(status_code=502, detail="CV review failed") from None
    return result.model_dump()


@router.delete("/{kind}")
async def revert_document(
    kind: str = kind_path,
    service: DocumentService = get_document_service_dep,
    tenant_id: TenantId = tenant_id_dep,
) -> dict[str, Any]:
    """Drop the stored document, reverting reads to the shipped JSON file.

    Not a destructive delete: the document still resolves, from its file
    fallback. This is the undo for a bad edit.
    """
    reverted = await service.revert_to_file(kind, tenant_id=tenant_id)
    return {"kind": kind, "reverted": reverted}
