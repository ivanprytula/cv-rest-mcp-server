import json
import re
import sys
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.constants import CONFIG_DIR
from app.dependencies import get_pdf_service
from app.pdf_generator import ThemeNotFoundError
from app.rate_limiter import limiter, limits
from app.renderer import render_html, render_template


router = APIRouter()

get_pdf_service_dep = Depends(get_pdf_service)

MCP_CLIENTS_PATH = CONFIG_DIR / "mcp_clients.json"

_MCP_CLIENTS_REQUIRED_KEYS = {
    "id",
    "label",
    "file",
    "docs_url",
    "verified",
    "config_template",
}


def load_mcp_clients(path) -> list[dict]:
    """Parse and validate the MCP client tab definitions.

    Single source of truth shared with scripts/check_mcp_docs.py; a broken
    file aborts startup instead of silently rendering an empty section.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"MCP clients config missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"MCP clients config is not valid JSON ({path}): {exc}"
        ) from exc

    if not isinstance(data, list) or not data:
        raise RuntimeError(f"{path}: expected a non-empty list of client entries")
    for entry in data:
        missing = _MCP_CLIENTS_REQUIRED_KEYS - entry.keys()
        if missing:
            raise RuntimeError(
                f"{path}: entry {entry.get('id', '?')!r} missing keys {sorted(missing)}"
            )
    return data


_MCP_CLIENTS = load_mcp_clients(MCP_CLIENTS_PATH)


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


def _client_mcp_configs(mcp_url: str) -> list[dict]:
    """Per-client MCP snippets in each agent's native config format."""
    return [
        {
            **entry,
            "config_template": entry["config_template"].replace("{mcp_url}", mcp_url),
        }
        for entry in _MCP_CLIENTS
    ]


@router.get("/")
@limits("30/minute", "120/hour")
async def root(request: Request, pdf_service=get_pdf_service_dep):
    """Landing page introducing the CV owner, with ready-to-copy MCP config and PDF download."""
    cv = pdf_service.cv_data
    mcp_url = str(request.base_url).rstrip("/") + "/mcp"
    html = render_template(
        "landing.html",
        service_name="CV REST/MCP Server",
        cv_name=str(cv.get("name", "")).strip() or "CV REST/MCP Server",
        cv_title=str(cv.get("title", "")).strip(),
        description="Generate, preview, and download my CV as a themed PDF — or plug it into any MCP client.",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        mcp_clients=_client_mcp_configs(mcp_url),
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
