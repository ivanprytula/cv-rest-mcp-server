import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.dependencies import get_pdf_service
from app.pdf_generator import ThemeNotFoundError
from app.rate_limiter import limiter, limits
from app.renderer import render_html, render_template


router = APIRouter()

get_pdf_service_dep = Depends(get_pdf_service)


def _pdf_filename(cv: dict) -> str:
    def _safe(value: str) -> str:
        return re.sub(r"[^\w\s-]", "", str(value)).strip().replace(" ", "_")

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"CV_{_safe(cv.get('name', ''))}_{_safe(cv.get('title', ''))}_{stamp}.pdf"


def _consent_kwargs(company: str, consent: bool) -> dict:
    """Normalize recruiter input into render kwargs.

    A non-empty company name implies consent even if the checkbox was missed.
    """
    clean = re.sub(r"\s+", " ", company).strip()[:120]
    return {"consent": consent or bool(clean), "consent_company": clean}


@router.get("/")
@limits("30/minute", "120/hour")
async def root(request: Request, pdf_service=get_pdf_service_dep):
    """Landing page with ready-to-copy MCP client config and CV download form."""
    mcp_url = str(request.base_url).rstrip("/") + "/mcp"
    mcp_config = {
        "mcpServers": {
            "cv-mcp-agent": {"url": mcp_url},
        },
    }
    html = render_template(
        "landing.html",
        service_name="CV REST/MCP Server",
        description="Generate, preview, and download your CV as a themed PDF — or plug it into any MCP client.",
        mcp_config=json.dumps(mcp_config, indent=2),
        themes=pdf_service.list_themes(),
    )
    return HTMLResponse(content=html)


@router.get("/health")
@limiter.limit("60/minute")
async def health(request: Request):
    """Liveness probe: returns service status and the active CV source kind (file/GCS)."""
    pdf_service = getattr(request.app.state, "pdf_service", None)
    return {
        "status": "ok",
        "cv_source": pdf_service.cv_source_kind if pdf_service else "unknown",
    }


@router.get("/cv")
@limits("30/minute", "600/hour")
async def get_cv_json(request: Request, pdf_service=get_pdf_service_dep):
    """Return the raw CV data as JSON, exactly as served to renderers."""
    return pdf_service.cv_data


@router.get("/cv/html")
@limits("30/minute", "300/hour")
async def get_cv_html(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
):
    """Render the full CV page as HTML using the given theme (no toolbar chrome).

    With `consent` (or a non-empty `company`), appends the GDPR/RODO
    recruitment-consent clause, naming the company when provided.
    """
    if theme not in pdf_service.themes:
        raise ThemeNotFoundError(theme)
    html = render_html(
        pdf_service.cv_data,
        pdf_service.themes[theme].CSS,
        **_consent_kwargs(company, consent),
    )
    return HTMLResponse(content=html)


@router.get("/cv/preview")
@limits("30/minute", "300/hour")
async def preview_cv(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
):
    """Interactive preview page: theme picker toolbar embedding the rendered CV (/cv/html).

    Forwards `consent` / `company` to the embedded CV, the theme links,
    and the download button so previews match the final PDF.
    """
    if theme not in pdf_service.themes:
        raise ThemeNotFoundError(theme)
    kwargs = _consent_kwargs(company, consent)
    html = render_template(
        "preview.html",
        cv_name=pdf_service.cv_data.get("name", ""),
        theme=theme,
        themes=pdf_service.list_themes(),
        consent=kwargs["consent"],
        company=kwargs["consent_company"],
    )
    return HTMLResponse(content=html)


@router.get("/cv/pdf")
@limits("5/15minute", "15/hour")
async def get_cv_pdf(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
):
    """Generate the CV as a themed PDF and return it as a downloadable attachment.

    With `consent` (or a non-empty `company`), the PDF carries the
    GDPR/RODO recruitment-consent clause on its last page.
    """
    pdf_bytes = await pdf_service.generate_cv_pdf_async(
        theme, **_consent_kwargs(company, consent)
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_pdf_filename(pdf_service.cv_data)}"'
        },
    )
