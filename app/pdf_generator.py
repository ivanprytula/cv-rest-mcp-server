import asyncio
import hashlib
import importlib
import json
import os
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from weasyprint import HTML

from app.constants import PDF_CACHE_MAX_ENTRIES, PDF_EXECUTOR_MAX_WORKERS, THEMES_DIR
from app.renderer import render_html
from app.themes import Theme


_PDF_CACHE: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_PDF_EXECUTOR = ThreadPoolExecutor(max_workers=PDF_EXECUTOR_MAX_WORKERS)

THEMES: dict[str, Theme] = {}


def load_themes() -> dict[str, Theme]:
    """Load all theme modules from the themes directory.

    A valid theme module must satisfy the Theme Protocol (export CSS: str).
    """
    themes: dict[str, Theme] = {}
    for filename in os.listdir(THEMES_DIR):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            try:
                module = importlib.import_module(f"app.themes.{module_name}")
                if not isinstance(module, Theme):
                    raise TypeError(
                        f"Theme '{module_name}' does not satisfy the Theme protocol: "
                        f"missing required 'CSS: str' attribute"
                    )
                themes[module_name] = module
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to load theme '{module_name}': {exc}"
                ) from exc
    return themes


def clear_cache() -> None:
    """Clear the PDF cache. Useful for testing and data reloads."""
    _PDF_CACHE.clear()


def list_themes() -> list[str]:
    return list(THEMES.keys())


THEMES = load_themes()


def _cache_key(theme: str, cv_json: dict) -> tuple[str, str]:
    cv_hash = hashlib.sha256(json.dumps(cv_json, sort_keys=True).encode()).hexdigest()
    return theme, cv_hash


def _generate_pdf_sync(html: str) -> bytes:
    try:
        return HTML(string=html).write_pdf()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PDF generation failed") from exc


def _get_or_render_pdf(theme: str, cv_json: dict) -> bytes:
    """Shared cache lookup and render logic for sync/async paths."""
    key = _cache_key(theme, cv_json)
    if key in _PDF_CACHE:
        _PDF_CACHE.move_to_end(key)
        return _PDF_CACHE[key]

    html = render_html(cv_json, THEMES[theme].CSS)
    pdf = _generate_pdf_sync(html)

    _PDF_CACHE[key] = pdf
    _PDF_CACHE.move_to_end(key)
    if len(_PDF_CACHE) > PDF_CACHE_MAX_ENTRIES:
        _PDF_CACHE.popitem(last=False)

    return pdf


class ThemeNotFoundError(HTTPException):
    def __init__(self, theme: str) -> None:
        super().__init__(status_code=404, detail=f"Theme '{theme}' not found")


def generate_cv_pdf(theme: str, cv_json: dict) -> bytes:
    if theme not in THEMES:
        raise ThemeNotFoundError(theme)
    return _get_or_render_pdf(theme, cv_json)


async def generate_cv_pdf_async(theme: str, cv_json: dict) -> bytes:
    if theme not in THEMES:
        raise ThemeNotFoundError(theme)

    key = _cache_key(theme, cv_json)
    if key in _PDF_CACHE:
        _PDF_CACHE.move_to_end(key)
        return _PDF_CACHE[key]

    html = render_html(cv_json, THEMES[theme].CSS)
    loop = asyncio.get_event_loop()
    pdf = await loop.run_in_executor(_PDF_EXECUTOR, _generate_pdf_sync, html)

    _PDF_CACHE[key] = pdf
    _PDF_CACHE.move_to_end(key)
    if len(_PDF_CACHE) > PDF_CACHE_MAX_ENTRIES:
        _PDF_CACHE.popitem(last=False)

    return pdf
