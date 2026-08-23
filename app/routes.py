import json
import re
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.cv_data import CV_DATA
from app.pdf_generator import generate_cv_pdf_async, list_themes
from app.rate_limiter import limiter
from app.renderer import render_template


router = APIRouter()


def _pdf_filename(cv: dict) -> str:
    def _safe(value: str) -> str:
        return re.sub(r"[^\w\s-]", "", str(value)).strip().replace(" ", "_")

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"CV_{_safe(cv.get('name', ''))}_{_safe(cv.get('title', ''))}_{stamp}.pdf"


@router.get("/")
@limiter.limit("30/minute")
async def root(request: Request):
    mcp_url = str(request.base_url).rstrip("/") + "/mcp"
    mcp_config = {
        "mcpServers": {
            "cv-mcp-agent": {"url": mcp_url},
        },
    }
    endpoints = [
        {
            "method": "GET",
            "path": "/health",
            "url": "/health",
            "description": "Liveness check",
        },
        {
            "method": "GET",
            "path": "/cv",
            "url": "/cv",
            "description": "CV data as JSON",
        },
        {
            "method": "GET",
            "path": "/cv/pdf",
            "url": "/cv/pdf?theme=classic",
            "description": "Rendered CV as PDF (theme: classic|minimal|modern)",
        },
        {
            "method": "GET",
            "path": "/mcp",
            "url": mcp_url,
            "description": "MCP server endpoint",
        },
    ]
    html = render_template(
        "landing.html",
        service_name="CV MCP Agent",
        description="Generate and download your CV as a PDF, or connect via MCP.",
        mcp_url=mcp_url,
        mcp_config=json.dumps(mcp_config, indent=2),
        endpoints=endpoints,
        themes=list_themes(),
    )
    return HTMLResponse(content=html)


@router.get("/health")
@limiter.limit("60/minute")
async def health(request: Request):
    return {"status": "ok"}


@router.get("/cv")
@limiter.limit("30/minute")
async def get_cv_json(request: Request):
    return CV_DATA


@router.get("/cv/pdf")
@limiter.limit("5/15minute")
async def get_cv_pdf(request: Request, theme: str = "classic"):
    pdf_bytes = await generate_cv_pdf_async(theme, CV_DATA)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_pdf_filename(CV_DATA)}"'
        },
    )
