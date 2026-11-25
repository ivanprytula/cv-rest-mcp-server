"""Public REST endpoints for api-core without DB.

Provides: /, /health, /cv, /cv/html, /cv/preview, /cv/pdf
"""

import json
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from services.portfolio.constants import CONFIG_DIR
from services.portfolio.dependencies import get_pdf_service
from services.portfolio.pdf_generator import ThemeNotFoundError
from services.portfolio.rate_limiter import limits
from services.portfolio.renderer import render_html, render_template


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

_RESP_DETAIL_JSON = {
    "application/json": {
        "schema": {
            "type": "object",
            "properties": {"detail": {"type": "string"}},
        }
    }
}

_RESP_DESCRIPTIONS = {
    404: "Theme not found",
    413: "JD body exceeds the 10 MB payload cap",
    422: "Malformed or empty JD body",
    429: "Rate limit exceeded",
    500: "Internal server error",
    503: "Service not initialized",
}


def _responses(*codes: int) -> dict:
    return {c: _RESP_DETAIL_JSON for c in codes}


def _consent_kwargs(company: str, consent: bool) -> dict:
    """Normalize recruiter input into render kwargs."""
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


@router.get("/", tags=["Pages"], responses=_responses(429))
async def landing(request: Request, pdf_service=get_pdf_service_dep) -> HTMLResponse:
    """Landing page with theme picker, MCP config, and API table."""
    cv = await pdf_service.cv_data()
    mcp_url = str(request.base_url).rstrip("/") + "/mcp"
    html = render_template(
        "landing.html",
        service_name="CV REST/MCP Server",
        cv_name=str(cv.get("name", "")).strip() or "CV REST/MCP Server",
        cv_title=str(cv.get("title", "")).strip(),
        cv_summary=str(cv.get("summary", "")).strip(),
        cv_location=str(cv.get("location", "")).strip(),
        cv_github=str(cv.get("github", "")).strip(),
        cv_linkedin=str(cv.get("linkedin", "")).strip(),
        cv_telegram=str(cv.get("telegram", "")).strip(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        mcp_clients=_client_mcp_configs(mcp_url),
        themes=pdf_service.list_themes(),
    )
    return HTMLResponse(content=html)


@router.get("/health", tags=["System"], responses=_responses(429))
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/cv", tags=["CV"], responses=_responses(429, 503))
async def cv_json(pdf_service=get_pdf_service_dep) -> dict:
    """Return the live CV as JSON."""
    return await pdf_service.cv_data()


@router.get("/cv/html", tags=["CV"], responses=_responses(404, 429, 503))
async def cv_html(
    request: Request,
    theme: str = "modern",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
) -> HTMLResponse:
    """Render the CV as an HTML page with the given theme."""
    if theme not in pdf_service.themes:
        raise ThemeNotFoundError(theme)
    cv = await pdf_service.cv_data()
    html = render_html(
        cv, pdf_service.themes[theme].CSS, **_consent_kwargs(company, consent)
    )
    return HTMLResponse(content=html)


@router.get("/cv/preview", tags=["Pages"], responses=_responses(404, 429, 503))
async def cv_preview(
    request: Request,
    theme: str = "modern",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
) -> HTMLResponse:
    """Preview page with toolbar embedding /cv/html in an iframe."""
    if theme not in pdf_service.themes:
        raise ThemeNotFoundError(theme)
    cv = await pdf_service.cv_data()
    kwargs = _consent_kwargs(company, consent)
    html = render_template(
        "preview.html",
        cv_name=cv.get("name", ""),
        theme=theme,
        themes=pdf_service.list_themes(),
        consent=kwargs["consent"],
        company=kwargs["consent_company"],
    )
    return HTMLResponse(content=html)


@router.get("/cv/pdf", tags=["CV"], responses=_responses(404, 429, 503))
@limits("5/15minute", "15/hour")
async def cv_pdf(
    request: Request,
    theme: str = "modern",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
) -> Response:
    """Download the CV as a themed PDF."""
    cv = await pdf_service.cv_data()
    pdf_bytes = await pdf_service.generate_cv_pdf_async(
        theme, cv, **_consent_kwargs(company, consent)
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="cv-{theme}.pdf"'},
    )


def load_mcp_clients(path: Path) -> list[dict]:
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


# The /api/v1/cv and /api/v1/cv/pdf endpoints require auth and DB, so they are
# not included in this api-core build. See the DB-backed version in the main
# branch for those endpoints.
