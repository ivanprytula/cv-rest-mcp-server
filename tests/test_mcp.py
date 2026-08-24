import base64

import pytest
from fastmcp.exceptions import ToolError

from app.main import app, generate_cv_pdf_tool, get_available_themes, get_cv


@pytest.fixture(autouse=True)
def _setup_pdf_service(override_pdf_service):
    yield


def test_get_cv_tool(synthetic_cv):
    result = get_cv()
    assert result["name"] == synthetic_cv["name"]
    assert isinstance(result["skills"], list)
    assert isinstance(result["experience"], list)


def test_get_available_themes():
    result = get_available_themes()
    assert isinstance(result, list)
    assert "classic" in result
    assert "minimal" in result
    assert "modern" in result
    assert "original" in result


async def test_generate_cv_pdf_tool_invalid_theme():
    with pytest.raises(ToolError, match="Theme 'nonexistent' not found"):
        await generate_cv_pdf_tool("nonexistent")


async def test_generate_cv_pdf_tool_returns_base64_pdf():
    result = await generate_cv_pdf_tool("classic")
    decoded = base64.b64decode(result)
    assert decoded.startswith(b"%PDF")


async def test_generate_cv_pdf_tool_sanitizes_internal_errors(pdf_service, monkeypatch):
    def broken_html(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr("app.pdf_generator.HTML", broken_html)
    with pytest.raises(ToolError, match="PDF generation failed") as exc_info:
        await generate_cv_pdf_tool("classic")
    assert "render exploded" not in str(exc_info.value)
    assert len(pdf_service._cache) == 0


async def test_mcp_tools_raise_without_initialized_service():
    app.state.pdf_service = None
    with pytest.raises(RuntimeError, match="PDF service not initialized"):
        get_cv()
    with pytest.raises(RuntimeError, match="PDF service not initialized"):
        get_available_themes()
    with pytest.raises(RuntimeError, match="PDF service not initialized"):
        await generate_cv_pdf_tool("classic")


async def test_mcp_endpoint_redirect(client):
    resp = await client.get("/mcp", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"].endswith("/mcp/")
