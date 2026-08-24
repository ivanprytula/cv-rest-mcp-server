import pytest
from fastapi import HTTPException

from app.cv_source import CvSource
from app.pdf_generator import PdfService


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


def test_cache_evicts_least_recently_used_entry(synthetic_cv_path):
    service = PdfService(
        CvSource.for_path(synthetic_cv_path), max_entries=1, max_workers=1
    )
    service.generate_cv_pdf("classic")
    service.generate_cv_pdf("minimal")
    assert [theme for theme, _ in service._cache] == ["minimal"]


def test_generate_cv_pdf_wraps_render_errors(pdf_service, monkeypatch):
    def broken_html(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr("app.pdf_generator.HTML", broken_html)
    with pytest.raises(HTTPException) as exc_info:
        pdf_service.generate_cv_pdf("classic")
    assert exc_info.value.status_code == 500
    assert len(pdf_service._cache) == 0
