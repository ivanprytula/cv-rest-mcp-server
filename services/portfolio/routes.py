import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from services.portfolio.constants import API_V1_PREFIX, CONFIG_DIR
from services.portfolio.dependencies import get_pdf_service, get_revision_service
from services.portfolio.jd_input import PayloadTooLargeError, parse_jd_input
from services.portfolio.matching.baseline import BaselineError, get_baseline
from services.portfolio.matching.tailor import tailor_cv
from services.portfolio.pdf_generator import ThemeNotFoundError
from services.portfolio.rate_limiter import limiter, limits
from services.portfolio.renderer import render_html, render_template
from services.portfolio.revisions.revision_service import RevisionService
from services.portfolio.schemas.tailor import RevisionSummary
from services.portfolio.settings import settings


logger = logging.getLogger(__name__)

router = APIRouter()

get_pdf_service_dep = Depends(get_pdf_service)
get_revision_service_dep = Depends(get_revision_service)

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


def _load_tailored_revision_from_file(name: str, *, default: dict) -> dict:
    """File-glob fallback: resolve a bare ``cv_tailored-<ts>.json`` filename
    (the pre-Postgres selector shape) or ``latest`` from ``settings.cv_tailored_dir``.

    Only ``.json`` files directly inside that directory are accepted — path
    separators and everything else is rejected.
    """
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


async def _load_tailored_revision(
    selector: str, *, default: dict, revision_service: RevisionService | None
) -> dict:
    """Resolve an optional ``?tailored=`` revision selector to a CV dict.

    ``selector`` is the numeric ``id`` returned by ``/api/v1/cv/tailor`` in
    ``saved_to`` (or the literal ``latest``), looked up in Postgres first.
    On any DB error (or a selector predating Postgres — a bare
    ``cv_tailored-<ts>.json`` filename), falls back to the file-glob path
    (degrade-don't-crash, mirrors ``CvSource``). An empty ``selector`` falls
    back to the live CV without ever touching ``revision_service`` — the
    public, untailored surface (most traffic on ``/cv/html`` etc.) must stay
    independent of whether the revision service initialized at all.
    ``revision_service`` is only ``None`` if the app never wired it up
    (503, matching every other uninitialized-service case in this app).
    """
    if not selector:
        return default
    if revision_service is None:
        raise HTTPException(status_code=503, detail="Revision service not initialized")

    selector = selector.strip().strip("/\\")

    if selector == "latest":
        revisions = await revision_service.list_all()
        if revisions:
            return revisions[0].tailored_cv
        return _load_tailored_revision_from_file(selector, default=default)

    if selector.endswith(".json"):
        # Legacy filename-shaped selector — never a Postgres id.
        return _load_tailored_revision_from_file(selector, default=default)

    if selector.isdigit():
        revision = await revision_service.get_by_id(int(selector))
        if revision is not None:
            return revision.tailored_cv
    return _load_tailored_revision_from_file(selector, default=default)


def _revision_summary_from_file(path: Path) -> RevisionSummary:
    stat = path.stat()
    return RevisionSummary(
        id=path.name,
        name=path.name,
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        size_bytes=stat.st_size,
    )


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
    """Return the raw CV data as JSON, exactly as served to renderers.

    Public, unauthenticated, live-CV-only — see /api/v1/cv for the
    operator-only tailored equivalent.
    """
    return pdf_service.cv_data


@router.get(f"{API_V1_PREFIX}/cv", tags=["CV"], responses=_responses(404, 429, 503))
@limits("30/minute", "600/hour")
async def get_tailored_cv_json(
    request: Request,
    tailored: str = "latest",
    pdf_service=get_pdf_service_dep,
    revision_service=get_revision_service_dep,
):
    """Return a tailored revision's raw CV JSON (operator console only).

    Requires a JWT with the `cv:read` scope (see JWTAuthMiddleware). `tailored`
    is the revision `id` from /api/v1/cv/tailor's `saved_to`, or the literal
    `latest`. Powers the SPA's revision-preview page.
    """
    return await _load_tailored_revision(
        tailored, default=pdf_service.cv_data, revision_service=revision_service
    )


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
    `tailored` (the revision `id` from /api/v1/cv/tailor's `saved_to`, or
    `latest`), renders that revision instead of the live CV.

    `tailored` is the only path that touches the revision service — most
    traffic here is the public, untailored page, which must stay reachable
    even if the revision service never initialized (no Depends() on it).
    """
    if theme not in pdf_service.themes:
        raise ThemeNotFoundError(theme)
    cv = await _load_tailored_revision(
        tailored,
        default=pdf_service.cv_data,
        revision_service=getattr(request.app.state, "revision_service", None),
    )
    html = render_html(
        cv,
        pdf_service.themes[theme].CSS,
        **_consent_kwargs(company, consent),
    )
    return HTMLResponse(content=html)


@router.get("/cv/preview", tags=["Pages"], responses=_responses(429, 503))
@limits("30/minute", "300/hour")
async def preview_cv(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
):
    """Interactive preview page: theme picker toolbar embedding the live CV (/cv/html).

    Forwards `consent` / `company` to the embedded CV, the theme links, and the
    download button so previews match the final PDF. Public, unauthenticated,
    live-CV-only surface — tailored revisions are previewed only in the
    operator SPA (see /revisions/:name), never here.
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


async def _render_cv_pdf_response(
    cv: dict, theme: str, company: str, consent: bool, pdf_service
) -> Response:
    pdf_bytes = await pdf_service.generate_cv_pdf_async(
        theme, cv, **_consent_kwargs(company, consent)
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_pdf_filename(cv)}"'},
    )


@router.get("/cv/pdf", tags=["CV"], responses=_responses(404, 429, 503))
@limits("5/15minute", "15/hour")
async def get_cv_pdf(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    pdf_service=get_pdf_service_dep,
):
    """Generate the live CV as a themed PDF and return it as a downloadable attachment.

    With `consent` (or a non-empty `company`), the PDF carries the
    GDPR/RODO recruitment-consent clause on its last page. Public, unauthenticated
    surface — tailored revisions are never reachable here; see
    `/api/v1/cv/pdf` for the authenticated, operator-only equivalent.
    """
    return await _render_cv_pdf_response(
        pdf_service.cv_data, theme, company, consent, pdf_service
    )


@router.get(f"{API_V1_PREFIX}/cv/pdf", tags=["CV"], responses=_responses(404, 429, 503))
@limits("5/15minute", "15/hour")
async def get_tailored_cv_pdf(
    request: Request,
    theme: str = "classic",
    company: str = "",
    consent: bool = False,
    tailored: str = "latest",
    pdf_service=get_pdf_service_dep,
    revision_service=get_revision_service_dep,
):
    """Generate a tailored CV revision as a themed PDF (operator console only).

    Requires a JWT with the `cv:read` scope (see JWTAuthMiddleware). `tailored`
    is the revision `id` from /api/v1/cv/tailor's `saved_to`, or the literal
    `latest`. Powers the SPA's revision-preview download button; the public
    `/cv/pdf` never accepts a `tailored` selector.
    """
    cv = await _load_tailored_revision(
        tailored, default=pdf_service.cv_data, revision_service=revision_service
    )
    return await _render_cv_pdf_response(cv, theme, company, consent, pdf_service)


@router.post(
    f"{API_V1_PREFIX}/cv/tailor",
    tags=["CV"],
    responses=_responses(413, 422, 429, 500, 503),
)
@limits("10/minute", "60/hour")
async def tailor_cv_endpoint(
    request: Request,
    pdf_service=get_pdf_service_dep,
    revision_service=get_revision_service_dep,
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
    ``saved_to`` — the new revision's `id` (Postgres-backed; degrades to a
    ``cv_tailored-<UTC-timestamp>.json`` file path in ``settings.cv_tailored_dir``
    on any DB error) the operator may promote.

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

    revision = await revision_service.create(jd_text=jd.jd_text, tailored_cv=tailored)
    if revision is not None:
        return {**tailored, "saved_to": str(revision.id)}

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

    return {**tailored, "saved_to": revision_path.name}


@router.get(f"{API_V1_PREFIX}/revisions", tags=["CV"], responses=_responses(429, 503))
@limits("30/minute", "300/hour")
async def list_tailored_revisions(
    request: Request, revision_service=get_revision_service_dep
):
    """List tailored CV revisions written by ``/api/v1/cv/tailor``, newest first.

    Requires the `cv:read` scope (same as the `?tailored=` revision reads).
    Reads Postgres first; falls back to the file-glob path (degrade-don't-
    crash) only when Postgres has no rows yet — a DB error surfaces as an
    empty list from `RevisionService.list_all()`, same as "no rows".
    """
    revisions = await revision_service.list_all()
    if revisions:
        return {
            "revisions": [
                RevisionSummary(
                    id=str(r.id),
                    name=r.name,
                    created_at=r.created_at.isoformat(),
                    size_bytes=len(json.dumps(r.tailored_cv)),
                )
                for r in revisions
            ]
        }

    files = sorted(
        settings.cv_tailored_dir.glob("cv_tailored-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return {"revisions": [_revision_summary_from_file(p) for p in files]}
