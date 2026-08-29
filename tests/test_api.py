import json
import re
from pathlib import Path
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


async def test_openapi_declares_tailor_bearer_auth(client):
    # Swagger UI's Authorize button is wired to the Bearer scheme on /cv/tailor
    # AND the ?tailored= revision reads, so a recruiter-op can try them from
    # /docs without copy-pasting headers.
    resp = await client.get("/openapi.json")
    assert resp.status_code == status.HTTP_200_OK
    schema = resp.json()
    schemes = schema["components"]["securitySchemes"]
    assert schemes["HTTPBearer"] == {"type": "http", "scheme": "bearer"}
    operation = schema["paths"]["/cv/tailor"]["post"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "requestBody" in operation
    # The tailored revision reads carry the same requirement so the Authorize
    # button attaches the header to them too.
    for path in ("/cv/html", "/cv/preview", "/cv/pdf"):
        assert schema["paths"][path]["get"]["security"] == [{"HTTPBearer": []}]
    # Fully public routes must not carry the security requirement.
    assert "security" not in schema["paths"]["/cv"]["get"]


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


async def test_csp_header_present(client):
    response = await client.get("/health")
    assert "content-security-policy" in response.headers
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]


async def test_csp_script_hashes_match_templates(client):
    import base64
    import hashlib
    import re

    from app.constants import TEMPLATE_DIR

    csp = (await client.get("/health")).headers["content-security-policy"]
    script_directive = csp.split("script-src")[1].split(";")[0]

    expected_hashes = set()
    for path in sorted(TEMPLATE_DIR.rglob("*.html")):
        for script in re.findall(
            r"<script>(.*?)</script>", path.read_text(), re.DOTALL
        ):
            digest = hashlib.sha256(script.encode()).digest()
            expected_hashes.add(f"'sha256-{base64.b64encode(digest).decode()}'")

    assert len(expected_hashes) >= 4
    for h in expected_hashes:
        assert h in script_directive


async def test_csp_allows_google_fonts(client):
    csp = (await client.get("/health")).headers["content-security-policy"]
    assert "fonts.googleapis.com" in csp
    assert "fonts.gstatic.com" in csp
    style_src = csp.split("style-src")[1].split(";")[0]
    assert "fonts.googleapis.com" in style_src


async def test_csp_frame_src_self(client):
    csp = (await client.get("/health")).headers["content-security-policy"]
    assert "frame-src 'self'" in csp


async def test_csp_allows_swaggerui_cdn(client):
    csp = (await client.get("/health")).headers["content-security-policy"]
    script_src = csp.split("script-src")[1].split(";")[0]
    assert "cdn.jsdelivr.net" in script_src
    style_src = csp.split("style-src")[1].split(";")[0]
    assert "cdn.jsdelivr.net" in style_src
    img_src = csp.split("img-src")[1].split(";")[0]
    assert "fastapi.tiangolo.com" in img_src
    assert "data:" in img_src


async def test_csp_connect_src_self(client):
    csp = (await client.get("/health")).headers["content-security-policy"]
    connect_src = csp.split("connect-src")[1].split(";")[0]
    assert "'self'" in connect_src


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


async def test_tailor_cv_endpoint(client, override_pdf_service):
    resp = await client.post(
        "/cv/tailor",
        json={"jd_text": "Required: Python, FastAPI"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "Jane Doe"
    assert "skills" in data
    assert "additional_skills" in data
    assert "saved_to" in data


async def test_tailor_cv_skills_match_bank_atoms(client, override_pdf_service):
    # The synthetic bank's only vouched atom on SYNTHETIC_CV is pytest, so a
    # JD naming it must produce exactly the bank atom under its category_hint.
    resp = await client.post(
        "/cv/tailor",
        content=b"Required: pytest",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["skills"] == [
        {
            "name": "Testing and quality",
            "sub_categories": [{"name": "practices", "items": ["pytest"]}],
        }
    ]
    assert data["additional_skills"] == []


async def test_tailor_cv_no_match_rebuilds_empty_skills(client, override_pdf_service):
    resp = await client.post(
        "/cv/tailor",
        content=b"Required: Cobol on a Mainframe",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["skills"] == []
    assert data["additional_skills"] == []
    assert data["name"] == "Jane Doe"


async def test_tailor_cv_writes_revision_file_and_roundtrips(
    client, override_pdf_service, tmp_path
):
    import json as _json

    from app.cv_data import validate_cv_payload
    from app.settings import settings

    resp = await client.post(
        "/cv/tailor",
        content=b"Required: pytest",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert settings.cv_tailored_dir == tmp_path / "tailored"
    saved = data["saved_to"]
    assert saved.startswith(str(settings.cv_tailored_dir))
    assert "cv_tailored-" in saved and saved.endswith(".json")

    revision = _json.loads(Path(saved).read_text(encoding="utf-8"))
    assert revision["name"] == "Jane Doe"
    assert "saved_to" not in revision
    assert revision["skills"][0]["sub_categories"][0]["items"] == ["pytest"]

    validated = validate_cv_payload(revision)
    assert validated["name"] == "Jane Doe"


async def test_tailor_cv_missing_jd_text(client, override_pdf_service):
    resp = await client.post(
        "/cv/tailor",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    # our contract detail names the missing field
    assert "jd_text" in resp.text


async def test_tailor_cv_empty_body(client, override_pdf_service):
    resp = await client.post("/cv/tailor", content=b"")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_tailor_cv_invalid_json(client, override_pdf_service):
    resp = await client.post(
        "/cv/tailor",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_tailor_cv_raw_text_with_newlines(client, override_pdf_service):
    jd_with_linebreaks = "The Role\n\nYou will take ownership\n- Of the pipeline\n"
    resp = await client.post(
        "/cv/tailor",
        content=jd_with_linebreaks.encode(),
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "Jane Doe"
    assert "skills" in data


async def test_tailor_cv_raw_text_sends_invalid_json_as_jd(
    client, override_pdf_service
):
    resp = await client.post(
        "/cv/tailor",
        content=b"not json",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == status.HTTP_200_OK


async def test_tailor_cv_json_with_literal_newlines_is_422_not_500(
    client, override_pdf_service
):
    # Raw LF inside a JSON string is invalid JSON (JSON spec); the endpoint
    # must reject cleanly (422) instead of crashing (500).
    body = b'{"jd_text": "The Role\n\nYou will take ownership", "title": ""}'
    resp = await client.post(
        "/cv/tailor",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_tailor_cv_pdf_upload(client, override_pdf_service):
    from weasyprint import HTML

    pdf_bytes = HTML(
        string="<html><body><p>Required: Python, FastAPI</p></body></html>"
    ).write_pdf()
    resp = await client.post(
        "/cv/tailor",
        content=pdf_bytes,
        headers={"content-type": "application/pdf"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "Jane Doe"


async def test_tailor_cv_docx_upload(client, override_pdf_service):
    from io import BytesIO

    from docx import Document

    document = Document()
    document.add_paragraph("Required: Python, FastAPI, PostgreSQL")
    buffer = BytesIO()
    document.save(buffer)
    resp = await client.post(
        "/cv/tailor",
        content=buffer.getvalue(),
        headers={
            "content-type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        },
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "Jane Doe"


async def test_tailor_cv_corrupt_pdf_is_422_not_500(client, override_pdf_service):
    resp = await client.post(
        "/cv/tailor",
        content=b"%PDF not a real pdf",
        headers={"content-type": "application/pdf"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_tailor_cv_oversize_body_is_413(
    client, override_pdf_service, monkeypatch
):
    monkeypatch.setattr("app.jd_input.MAX_JD_PAYLOAD_BYTES", 100)
    resp = await client.post(
        "/cv/tailor",
        content=b"x" * 200,
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert "limit" in resp.text


async def test_tailor_cv_internal_error_is_500_sanitized(
    client, override_pdf_service, monkeypatch
):
    def boom(jd_text, baseline_atoms, live_cv, *, title=""):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("app.routes.tailor_cv", boom)
    resp = await client.post(
        "/cv/tailor",
        content=b"Required: Python",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert resp.json()["detail"] == "CV tailoring failed"
    assert "secret" not in resp.text


async def test_tailored_html_renders_revision(
    client, override_pdf_service, synthetic_cv
):
    from app.settings import settings

    revision = {**synthetic_cv, "name": "Tailored Jane"}
    rev_path = settings.cv_tailored_dir / "cv_tailored-2026-08-29_10-00-00.json"
    rev_path.parent.mkdir(parents=True, exist_ok=True)
    rev_path.write_text(json.dumps(revision), encoding="utf-8")

    for selector in (
        "cv_tailored-2026-08-29_10-00-00.json",
        "latest",
    ):
        resp = await client.get(f"/cv/html?tailored={selector}")
        assert resp.status_code == status.HTTP_200_OK
        assert "Tailored Jane" in resp.text

    live = await client.get("/cv/html")
    assert live.status_code == status.HTTP_200_OK
    assert "Tailored Jane" not in live.text


async def test_tailored_pdf_uses_revision(client, override_pdf_service, synthetic_cv):
    from app.settings import settings

    revision = {**synthetic_cv, "title": "Tailored Engineer"}
    rev_path = settings.cv_tailored_dir / "cv_tailored-2026-08-29_10-00-00.json"
    rev_path.parent.mkdir(parents=True, exist_ok=True)
    rev_path.write_text(json.dumps(revision), encoding="utf-8")

    override_pdf_service.generate_cv_pdf_async = AsyncMock(
        return_value=b"%PDF-1.7 fake"
    )
    resp = await client.get("/cv/pdf?tailored=latest")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"] == "application/pdf"
    override_pdf_service.generate_cv_pdf_async.assert_awaited_once_with(
        "classic", revision, consent=False, consent_company=""
    )
    pattern = r'attachment; filename="CV_Jane_Doe_Tailored_Engineer_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.pdf"'
    assert re.match(pattern, resp.headers["content-disposition"])


async def test_tailored_preview_forwards_revision(
    client, override_pdf_service, synthetic_cv
):
    from app.settings import settings

    revision = {**synthetic_cv, "name": "Tailored Jane"}
    rev_path = settings.cv_tailored_dir / "cv_tailored-2026-08-29_10-00-00.json"
    rev_path.parent.mkdir(parents=True, exist_ok=True)
    rev_path.write_text(json.dumps(revision), encoding="utf-8")

    resp = await client.get(
        "/cv/preview?tailored=cv_tailored-2026-08-29_10-00-00.json&token=test-token"
    )
    assert resp.status_code == status.HTTP_200_OK
    assert "Tailored Jane" in resp.text
    # the iframe + links carry the token so the browser can fetch them
    assert "tailored=cv_tailored-2026-08-29_10-00-00.json" in resp.text
    assert "token=test-token" in resp.text


async def test_tailored_revision_rejects_non_basename_paths(
    client, override_pdf_service, tmp_path
):
    for selector in ("../cv.json", "sub/cv_tailored-1.json", "/etc/passwd", "nope"):
        resp = await client.get(f"/cv/html?tailored={selector}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND, selector

    resp = await client.get("/cv/html?tailored=cv_tailored-2020-01-01_00-00-00.json")
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    resp = await client.get("/cv/html?tailored=latest")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
