import re
from unittest.mock import AsyncMock

from fastapi import status

from app.main import app


async def test_root(client, override_pdf_service):
    resp = await client.get("/")
    assert resp.status_code == status.HTTP_200_OK
    assert "text/html" in resp.headers["content-type"]
    assert "CV REST/MCP Server" in resp.text  # footer
    assert "Jane Doe" in resp.text  # hero: author name from cv_data
    assert "Backend Engineer" in resp.text  # hero: author title from cv_data
    assert "/mcp" in resp.text
    assert "/static/css/site.css" in resp.text
    assert "cdn.tailwindcss.com" not in resp.text
    assert "/cv/preview" in resp.text
    assert "/static/favicon.svg" in resp.text


async def test_favicon_served(client):
    resp = await client.get("/static/favicon.svg")
    assert resp.status_code == status.HTTP_200_OK
    assert "image/svg+xml" in resp.headers["content-type"]
    assert "<desc>" in resp.text


async def test_site_css_served(client):
    resp = await client.get("/static/css/site.css")
    assert resp.status_code == status.HTTP_200_OK
    assert "text/css" in resp.headers["content-type"]
    assert ".dark" in resp.text


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["status"] == "ok"
    assert body["cv_source"] in {"gcs", "file", "placeholder", "unknown"}


async def test_get_cv(client, override_pdf_service):
    resp = await client.get("/cv")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "Jane Doe"
    assert data["title"] == "Backend Engineer"
    for key in (
        "skills",
        "experience",
        "education",
        "languages",
        "projects",
        "certifications",
        "publications",
        "awards",
        "volunteering",
    ):
        assert isinstance(data[key], list)


async def test_get_cv_html_classic(client, override_pdf_service):
    resp = await client.get("/cv/html?theme=classic")
    assert resp.status_code == status.HTTP_200_OK
    assert "text/html" in resp.headers["content-type"]
    assert "Jane Doe" in resp.text
    assert "Georgia" in resp.text


async def test_get_cv_html_footer(client, override_pdf_service):
    resp = await client.get("/cv/html?theme=minimal")
    assert resp.status_code == status.HTTP_200_OK
    assert 'class="cv-footer"' in resp.text
    footer = resp.text.split('class="cv-footer"', 1)[1].split("</div>", 1)[0]
    assert "Jane Doe" in footer
    assert "Backend Engineer" in footer
    assert "jane.doe@example.com" in footer
    assert "Page" in footer
    assert "page-number" in footer


async def test_get_cv_html_invalid_theme(client, override_pdf_service):
    resp = await client.get("/cv/html?theme=nonexistent")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "Theme 'nonexistent' not found" in resp.json()["detail"]


async def test_cv_preview_page(client, override_pdf_service):
    resp = await client.get("/cv/preview?theme=modern")
    assert resp.status_code == status.HTTP_200_OK
    assert "text/html" in resp.headers["content-type"]
    assert "/cv/html?theme=modern" in resp.text
    assert "/cv/pdf?theme=modern" in resp.text
    assert "Download PDF" in resp.text
    for theme_name in ("classic", "minimal", "modern"):
        assert f"/cv/preview?theme={theme_name}" in resp.text


async def test_cv_preview_invalid_theme(client, override_pdf_service):
    resp = await client.get("/cv/preview?theme=nonexistent")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "Theme 'nonexistent' not found" in resp.json()["detail"]


async def test_get_cv_pdf_classic(client, override_pdf_service):
    override_pdf_service.generate_cv_pdf_async = AsyncMock(
        return_value=b"%PDF-1.7 fake"
    )
    resp = await client.get("/cv/pdf?theme=classic")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"] == "application/pdf"
    pattern = r'attachment; filename="CV_Jane_Doe_Backend_Engineer_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.pdf"'
    assert re.match(pattern, resp.headers["content-disposition"])
    assert resp.content == b"%PDF-1.7 fake"


async def test_get_cv_pdf_modern(client, override_pdf_service):
    override_pdf_service.generate_cv_pdf_async = AsyncMock(
        return_value=b"%PDF-1.7 fake"
    )
    resp = await client.get("/cv/pdf?theme=modern")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.7 fake"


async def test_get_cv_pdf_minimal(client, override_pdf_service):
    override_pdf_service.generate_cv_pdf_async = AsyncMock(
        return_value=b"%PDF-1.7 fake"
    )
    resp = await client.get("/cv/pdf?theme=minimal")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.7 fake"


async def test_get_cv_pdf_invalid_theme(client, override_pdf_service):
    resp = await client.get("/cv/pdf?theme=nonexistent")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "Theme 'nonexistent' not found" in resp.json()["detail"]


async def test_security_headers_present(client):
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_cors_allows_any_origin_without_credentials(client):
    response = await client.get("/health", headers={"Origin": "https://example.com"})
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


async def test_cv_pdf_rate_limit_returns_429_on_sixth_request(
    override_pdf_service, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from app.rate_limiter import limiter

    # Non-loopback peer so the loopback exemption does not apply.
    transport = ASGITransport(app=app, client=("198.51.100.77", 12345))
    limiter.reset()
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            statuses = []
            for _ in range(6):
                resp = await ac.get("/cv/pdf?theme=classic")
                statuses.append(resp.status_code)
    finally:
        limiter.reset()

    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert statuses[5] == status.HTTP_429_TOO_MANY_REQUESTS
