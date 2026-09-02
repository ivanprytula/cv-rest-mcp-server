import asyncio
import threading

import pytest
from fastapi import HTTPException
from weasyprint import HTML

from services.portfolio.cv_source import CvSource
from services.portfolio.pdf_generator import (
    PdfService,
    _deny_all_url_fetcher,
    _URLFetchDeniedError,
)


def test_list_themes(pdf_service):
    themes = pdf_service.list_themes()
    assert isinstance(themes, list)
    assert themes[0] == "original"
    assert "classic" in themes
    assert "minimal" in themes
    assert "modern" in themes


def test_generate_cv_pdf_invalid_theme(pdf_service):
    with pytest.raises(Exception) as exc_info:
        pdf_service.generate_cv_pdf("nonexistent")
    assert "Theme 'nonexistent' not found" in str(exc_info.value)


def test_generate_cv_pdf_returns_bytes(pdf_service):
    pdf = pdf_service.generate_cv_pdf("classic")
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://example.com",
        "https://example.com",
        "data:text/plain,blocked",
    ],
)
def test_deny_all_url_fetcher_rejects_urls(url):
    with pytest.raises(_URLFetchDeniedError):
        _deny_all_url_fetcher(url)


def test_weasyprint_html_uses_deny_all_url_fetcher():
    pdf = HTML(
        string='<img src="file:///etc/passwd">',
        url_fetcher=_deny_all_url_fetcher,
    ).write_pdf()

    assert pdf.startswith(b"%PDF")


def test_generate_cv_pdf_caches_result(pdf_service):
    pdf_service.clear_cache()
    pdf1 = pdf_service.generate_cv_pdf("classic")
    pdf2 = pdf_service.generate_cv_pdf("classic")
    assert pdf1 == pdf2
    assert len(pdf_service._cache) == 1


def test_generate_cv_pdf_different_themes_cached_separately(pdf_service):
    pdf_service.clear_cache()
    pdf_classic = pdf_service.generate_cv_pdf("classic")
    pdf_minimal = pdf_service.generate_cv_pdf("minimal")
    assert pdf_classic != pdf_minimal
    assert len(pdf_service._cache) == 2


async def test_generate_cv_pdf_async_returns_bytes(pdf_service):
    pdf = await pdf_service.generate_cv_pdf_async("minimal")
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")


async def test_generate_cv_pdf_async_uses_cache(pdf_service):
    pdf_service.clear_cache()
    pdf1 = await pdf_service.generate_cv_pdf_async("modern")
    pdf2 = await pdf_service.generate_cv_pdf_async("modern")
    assert pdf1 == pdf2


async def test_generate_cv_pdf_async_single_flight(pdf_service, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    render_count = 0
    original_render = pdf_service._render_pdf

    def render_once(*args, **kwargs):
        nonlocal render_count
        render_count += 1
        started.set()
        assert release.wait(timeout=5)
        return original_render(*args, **kwargs)

    monkeypatch.setattr(pdf_service, "_render_pdf", render_once)
    first = asyncio.create_task(pdf_service.generate_cv_pdf_async("classic"))
    await asyncio.to_thread(started.wait)
    second = asyncio.create_task(pdf_service.generate_cv_pdf_async("classic"))
    await asyncio.sleep(0)
    assert len(pdf_service._inflight) == 1
    release.set()

    pdf1, pdf2 = await asyncio.gather(first, second)

    assert render_count == 1
    assert pdf1 == pdf2
    assert len(pdf_service._cache) == 1


def test_cache_evicts_least_recently_used_entry(synthetic_cv_path):
    service = PdfService(
        CvSource(local_path=synthetic_cv_path), max_entries=1, max_workers=1
    )
    service.generate_cv_pdf("classic")
    service.generate_cv_pdf("minimal")
    assert [theme for theme, _ in service._cache] == ["minimal"]


def test_generate_cv_pdf_wraps_render_errors(pdf_service, monkeypatch):
    def broken_html(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr("services.portfolio.pdf_generator.HTML", broken_html)
    with pytest.raises(HTTPException) as exc_info:
        pdf_service.generate_cv_pdf("classic")
    assert exc_info.value.status_code == 500
    assert len(pdf_service._cache) == 0
