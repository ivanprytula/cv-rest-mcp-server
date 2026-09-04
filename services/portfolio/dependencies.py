from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

from services.portfolio.pdf_generator import PdfService


if TYPE_CHECKING:
    # Import-time only: services.portfolio.auth eagerly imports auth.routes,
    # which imports this module for get_user_service -- a real module-level
    # import here would be circular. The type hint doesn't need the runtime
    # class, only static analysis does.
    from services.portfolio.auth.refresh_token_service import RefreshTokenService
    from services.portfolio.auth.user_service import UserService
    from services.portfolio.gaps.gap_service import GapService
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


async def get_refresh_token_service(request: Request) -> RefreshTokenService:
    service = request.app.state.refresh_token_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Refresh token service not initialized",
        )
    return service
