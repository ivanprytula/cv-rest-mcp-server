from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

from services.portfolio.pdf_generator import PdfService
from services.portfolio.tenancy import TenantId


if TYPE_CHECKING:
    # Import-time only: services.portfolio.auth eagerly imports auth.routes,
    # which imports this module for get_user_service -- a real module-level
    # import here would be circular. The type hint doesn't need the runtime
    # class, only static analysis does.
    from services.portfolio.auth.refresh_token_service import RefreshTokenService
    from services.portfolio.auth.user_service import UserService
    from services.portfolio.cv_extraction import CVExtractionService
    from services.portfolio.documents.document_service import DocumentService
    from services.portfolio.gaps.gap_service import GapService
    from services.portfolio.gaps.tracked_board_service import TrackedBoardService
    from services.portfolio.revisions.revision_service import RevisionService


async def get_pdf_service(request: Request) -> PdfService:
    service = request.app.state.pdf_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF service not initialized",
        )
    return service


async def get_user_service(request: Request) -> UserService:
    service = request.app.state.user_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User service not initialized",
        )
    return service


async def get_revision_service(request: Request) -> RevisionService:
    service = request.app.state.revision_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Revision service not initialized",
        )
    return service


async def get_document_service(request: Request) -> DocumentService:
    service = getattr(request.app.state, "document_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document service not initialized",
        )
    return service


async def get_cv_extraction_service(request: Request) -> CVExtractionService:
    """The CV extraction service, or 503 when no API key is configured.

    Distinct from get_optional_gap_service's pattern: extraction has no
    degraded-but-working fallback, so an unconfigured key must reject the
    request rather than silently skip a step.
    """
    service = getattr(request.app.state, "cv_extraction_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CV extraction is not configured",
        )
    return service


async def get_optional_gap_service(request: Request) -> GapService | None:
    """The gap service if wired, else None.

    For callers that store a posting as a *side effect* (the tailoring
    endpoint): the feature must keep working when gap storage is
    unavailable, so an absent service is a skipped write, not a 503.
    """
    return getattr(request.app.state, "gap_service", None)


async def get_gap_service(request: Request) -> GapService:
    # getattr, not attribute access: Starlette's State raises AttributeError
    # for anything the lifespan never set, which would 500 instead of 503.
    service = getattr(request.app.state, "gap_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gap service not initialized",
        )
    return service


async def get_tracked_board_service(request: Request) -> TrackedBoardService:
    service = getattr(request.app.state, "tracked_board_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tracked board service not initialized",
        )
    return service


async def get_refresh_token_service(request: Request) -> RefreshTokenService:
    service = request.app.state.refresh_token_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Refresh token service not initialized",
        )
    return service


async def get_tenant_id(request: Request) -> TenantId:
    """The tenant this request acts on: the `uid` claim of its access token.

    One seam, so "which tenant is this?" has a single answer instead of each
    route inventing one. `uid` is the numeric user id rather than `sub` (a
    username, which can be changed), so a rename never reassigns documents.

    A verified token with no `uid` is one issued before tenancy existed. It
    is refused rather than guessed at: picking a tenant for it would mean
    handing someone another tenant's documents, and re-logging in mints a
    token that carries the claim.
    """
    claims = request.scope.get("auth")
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    uid = claims.get("uid")
    if not isinstance(uid, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token predates tenant support; sign in again",
        )
    return TenantId(uid)
