from fastapi import HTTPException, Request, status

from services.portfolio.pdf_generator import PdfService


async def get_pdf_service(request: Request) -> PdfService:
    service = request.app.state.pdf_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF service not initialized",
        )
    return service
