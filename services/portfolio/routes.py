import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from services.portfolio.constants import API_V1_PREFIX, CONFIG_DIR
from services.portfolio.dependencies import get_pdf_service
from services.portfolio.jd_input import PayloadTooLargeError, parse_jd_input
from services.portfolio.matching.baseline import BaselineError, get_baseline
from services.portfolio.matching.tailor import tailor_cv
from services.portfolio.pdf_generator import ThemeNotFoundError
from services.portfolio.rate_limiter import limiter, limits
from services.portfolio.renderer import render_html, render_template
from services.portfolio.settings import settings


logger = logging.getLogger(__name__)

router = APIRouter()

get_pdf_service_dep = Depends(get_pdf_service)

MCP_CLIENTS_PATH = CONFIG_DIR / "mcp_clients.json"

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
    503: "CV source or PDF service unavailable",
}


def _responses(*codes: int) -> dict:
    """Declare the documented error responses for a route in OpenAPI."""
    return {
        code: {"description": _RESP_DESCRIPTIONS[code], "content": _RESP_DETAIL_JSON}
        for code in codes
    }


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


def _load_tailored_revision(name: str, *, default: dict) -> dict:
    """Resolve an optional ``?tailored=`` revision selector to a CV dict.

    ``name`` is the bare ``cv_tailored-<UTC timestamp>.json`` filename
    returned by ``/api/v1/cv/tailor`` in ``saved_to``, or the literal ``latest`` for
    the most recently written revision (timestamps sort chronologically).
    Only ``.json`` files directly inside ``settings.cv_tailored_dir`` are
    accepted — path separators and everything else is rejected — and an empty
    ``name`` falls back to the live CV.
    """
    if not name:
        return default

    name = name.strip().strip("/\\")
    if name == "latest":
        candidates = sorted(settings.cv_tailored_dir.glob("cv_tailored-*.json"))
        if not candidates:
            raise HTTPException(
                status_code=404, detail="No tailored CV revisions written yet"
            )
        revision_path = candidates[-1]
    elif name != Path(name).name or not name.endswith(".json"):
        raise HTTPException(
            status_code=404, detail="Tailored revision must be a bare .json filename"
        )
    else:
        revision_path = settings.cv_tailored_dir / name

    try:
        revision = json.loads(revision_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=404, detail="Tailored CV revision not found"
        ) from exc
    if not isinstance(revision, dict):
        raise HTTPException(
            status_code=404, detail="Tailored CV revision is not a CV object"
        )
    return revision


def _revision_summary(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "created_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "size_bytes": stat.st_size,
    }


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
        games_base_url=settings.games_base_url.rstrip("/"),
    )
    return HTMLResponse(content=html)


@router.get("/health", tags=["System"], responses=_responses(429))
@limiter.limit("60/minute")
async def health(request: Request):
    """Liveness probe: returns service status and the active CV source kind (file/GCS)."""
    pdf_service = getattr(request.app.state, "pdf_service", None)
    return {
        "status": "ok",
        "cv_source": pdf_service.cv_source_kind if pdf_service else "unknown",
    }


@router.get("/cv", tags=["CV"], responses=_responses(429, 503))
@limits("30/minute", "600/hour")
async def get_cv_json(request: Request, pdf_service=get_pdf_service_dep):
    """Return the raw CV data as JSON, exactly as served to renderers."""
    return pdf_service.cv_data


@router.get("/cv/html", tags=["CV"], responses=_responses(404, 429, 503))
@limits("30/minute", "300/hour")
async def get_cv_html(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    tailored: str = "",
    pdf_service=get_pdf_service_dep,
):
    """Render the full CV page as HTML using the given theme (no toolbar chrome).

    With `consent` (or a non-empty `company`), appends the GDPR/RODO
    recruitment-consent clause, naming the company when provided. With
    `tailored` (a bare `cv_tailored-<ts>.json` filename from /api/v1/cv/tailor's
    `saved_to`, or `latest`), renders that revision instead of the live CV.
    """
    if theme not in pdf_service.themes:
        raise ThemeNotFoundError(theme)
    cv = _load_tailored_revision(tailored, default=pdf_service.cv_data)
    html = render_html(
        cv,
        pdf_service.themes[theme].CSS,
        **_consent_kwargs(company, consent),
    )
    return HTMLResponse(content=html)


@router.get("/cv/preview", tags=["Pages"], responses=_responses(404, 429, 503))
@limits("30/minute", "300/hour")
async def preview_cv(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    tailored: str = "",
    pdf_service=get_pdf_service_dep,
):
    """Interactive preview page: theme picker toolbar embedding the rendered CV (/cv/html).

    Forwards `consent` / `company` / `tailored` / `token` to the embedded CV,
    the theme links, and the download button so previews match the final PDF.
    """
    if theme not in pdf_service.themes:
        raise ThemeNotFoundError(theme)
    cv = _load_tailored_revision(tailored, default=pdf_service.cv_data)
    kwargs = _consent_kwargs(company, consent)
    html = render_template(
        "preview.html",
        cv_name=cv.get("name", ""),
        theme=theme,
        themes=pdf_service.list_themes(),
        consent=kwargs["consent"],
        company=kwargs["consent_company"],
        tailored=tailored,
        token=request.query_params.get("token", ""),
    )
    return HTMLResponse(content=html)


@router.get("/cv/pdf", tags=["CV"], responses=_responses(404, 429, 503))
@limits("5/15minute", "15/hour")
async def get_cv_pdf(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    tailored: str = "",
    pdf_service=get_pdf_service_dep,
):
    """Generate the CV as a themed PDF and return it as a downloadable attachment.

    With `consent` (or a non-empty `company`), the PDF carries the
    GDPR/RODO recruitment-consent clause on its last page. With `tailored`
    (a bare `cv_tailored-<ts>.json` filename from /api/v1/cv/tailor's `saved_to`,
    or `latest`), renders that revision instead of the live CV.
    """
    cv = _load_tailored_revision(tailored, default=pdf_service.cv_data)
    pdf_bytes = await pdf_service.generate_cv_pdf_async(
        theme, cv, **_consent_kwargs(company, consent)
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_pdf_filename(cv)}"'},
    )


@router.post(
    f"{API_V1_PREFIX}/cv/tailor",
    tags=["CV"],
    responses=_responses(413, 422, 429, 500, 503),
)
@limits("10/minute", "60/hour")
async def tailor_cv_endpoint(
    request: Request,
    pdf_service=get_pdf_service_dep,
):
    """Match a job description against the skill bank and emit a tailored CV revision.

    The JD can be sent in several formats (max 10 MB) — a supported
    ``Content-Type`` is honored, a generic one is sniffed by magic bytes,
    and anything unexpected is treated as raw JD text:

    * Raw text / txt — the whole body is the JD.
    * Markdown — the whole body is the JD (syntax left intact for the matcher).
    * JSON — ``{"jd_text": "...", "title": ""}``.
    * PDF — ``application/pdf``.
    * DOCX — ``application/vnd.openxmlformats-officedocument.wordprocessingml.document``.

    Skills come from the **skill bank** (``data/cv_baseline.json``), not the
    live CV: JD qualifiers ("Solid experience with X" → expert) filter bank
    atoms by level, and the trust policy drops any matched atom the operator
    has not vouched for on the live CV. The response is the tailored CV plus
    ``saved_to`` pointing at the freshly written
    ``cv_tailored-<UTC-timestamp>.json`` revision in ``settings.cv_tailored_dir``
    (default ``data/tailored/``) the operator may promote.

    ``?title=`` overrides the CV title; a ``title`` inside the JSON payload
    wins for the JSON format.
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

    try:
        baseline_atoms = get_baseline()
    except BaselineError as exc:
        logger.warning("Skill bank unavailable: %s", exc)
        raise HTTPException(status_code=500, detail="CV tailoring failed") from None

    try:
        tailored = tailor_cv(
            jd.jd_text, baseline_atoms, pdf_service.cv_data, title=jd.title
        )
    except Exception:
        logger.exception("CV tailoring failed")
        raise HTTPException(status_code=500, detail="CV tailoring failed") from None

    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    revision_path = settings.cv_tailored_dir / f"cv_tailored-{stamp}.json"
    try:
        revision_path.parent.mkdir(parents=True, exist_ok=True)
        revision_path.write_text(
            json.dumps(tailored, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.exception("Failed to write tailored CV revision")
        raise HTTPException(status_code=500, detail="CV tailoring failed") from exc

    return {**tailored, "saved_to": str(revision_path)}


@router.get(f"{API_V1_PREFIX}/revisions", tags=["CV"], responses=_responses(429, 503))
@limits("30/minute", "300/hour")
async def list_tailored_revisions(request: Request):
    """List tailored CV revisions written by ``/api/v1/cv/tailor``, newest first.

    Requires the `cv:read` scope (same as the `?tailored=` revision reads).
    """
    revisions = sorted(
        settings.cv_tailored_dir.glob("cv_tailored-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return {"revisions": [_revision_summary(p) for p in revisions]}
