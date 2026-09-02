"""Recruiter consent clause (GDPR/RODO) across HTML, preview, and PDF paths."""

import pytest


pytestmark = pytest.mark.usefixtures("override_pdf_service")


async def test_html_without_consent_has_no_clause(client):
    r = await client.get("/cv/html", params={"theme": "classic"})
    assert r.status_code == 200
    assert 'class="consent"' not in r.text
    assert "art. 6 ust. 1 lit. a" not in r.text


async def test_html_with_consent_and_company(client):
    r = await client.get(
        "/cv/html",
        params={"theme": "classic", "consent": "1", "company": "Acme Corp"},
    )
    assert r.status_code == 200
    assert "art. 6 ust. 1 lit. a RODO" in r.text
    assert "Article 6(1)(a) of the GDPR" in r.text
    assert "<strong>Acme Corp</strong>" in r.text


async def test_company_alone_implies_consent(client):
    r = await client.get("/cv/html", params={"theme": "classic", "company": "Acme"})
    assert r.status_code == 200
    assert "RODO" in r.text
    assert "<strong>Acme</strong>" in r.text


async def test_html_escapes_company_name(client):
    r = await client.get(
        "/cv/html",
        params={"theme": "classic", "consent": "1", "company": "<b>Evil</b> & Co"},
    )
    assert r.status_code == 200
    assert "&lt;b&gt;Evil&lt;/b&gt; &amp; Co" in r.text
    assert "<b>Evil</b>" not in r.text


async def test_preview_forwards_params_to_links_and_iframe(client):
    r = await client.get(
        "/cv/preview",
        params={"theme": "classic", "consent": "1", "company": "Acme Sp. z o.o."},
    )
    assert r.status_code == 200
    assert "consent=1" in r.text
    assert "company=Acme+Sp.+z+o.o." in r.text or "company=Acme%20Sp." in r.text
    assert 'src="/cv/html?theme=classic' in r.text


async def test_pdf_cache_separates_companies(pdf_service):
    plain = await pdf_service.generate_cv_pdf_async("classic")
    acme = await pdf_service.generate_cv_pdf_async(
        "classic", consent=True, consent_company="Acme"
    )
    other = await pdf_service.generate_cv_pdf_async(
        "classic", consent=True, consent_company="Other"
    )

    assert plain != acme != other

    # Case/whitespace variants normalize to the same cache entry.
    again = await pdf_service.generate_cv_pdf_async(
        "classic", consent=True, consent_company="  ACME "
    )
    assert again == acme

    # Repeat hit is served from cache (identical bytes).
    repeat = await pdf_service.generate_cv_pdf_async(
        "classic", consent=True, consent_company="Acme"
    )
    assert repeat == acme
