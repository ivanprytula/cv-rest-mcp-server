import asyncio
import hashlib
import importlib
import json
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from weasyprint import HTML

from app.constants import PDF_CACHE_MAX_ENTRIES, PDF_EXECUTOR_MAX_WORKERS, THEMES_DIR
from app.cv_source import CvSource
from app.renderer import render_html
from app.themes import Theme


def load_themes() -> dict[str, Theme]:
    """Load all theme modules from the themes directory.

    "original" is the flagship look and is always listed first;
    remaining themes are ordered alphabetically for determinism.
    """
    discovered: dict[str, Theme] = {}
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
                discovered[module_name] = module
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to load theme '{module_name}': {exc}"
                ) from exc
    ordered_names = sorted(discovered, key=lambda name: (name != "original", name))
    return {name: discovered[name] for name in ordered_names}


def _generate_pdf_sync(html: str) -> bytes:
    try:
        return HTML(string=html).write_pdf()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PDF generation failed") from exc


class ThemeNotFoundError(HTTPException):
    def __init__(self, theme: str) -> None:
        super().__init__(status_code=404, detail=f"Theme '{theme}' not found")


class PdfService:
    def __init__(
        self,
        cv_source: CvSource,
        *,
        max_entries: int = PDF_CACHE_MAX_ENTRIES,
        max_workers: int = PDF_EXECUTOR_MAX_WORKERS,
    ) -> None:
        self._cv_source = cv_source
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.themes: dict[str, Theme] = load_themes()
        self._cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    @property
    def cv_data(self) -> dict:
        """Current CV document (hot-reloaded when backed by GCS)."""
        return self._cv_source.get()

    @property
    def cv_source_kind(self) -> str:
        """Where the served CV came from: "gcs", "file", or "placeholder"."""
        return self._cv_source.source_kind

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def list_themes(self) -> list[str]:
        return list(self.themes.keys())

    def _cache_key(self, theme: str, cv_json: dict) -> tuple[str, str]:
        cv_hash = hashlib.sha256(
            json.dumps(cv_json, sort_keys=True).encode()
        ).hexdigest()
        return theme, cv_hash

    def _cache_get(self, key: tuple[str, str]) -> bytes | None:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def _cache_put(self, key: tuple[str, str], pdf: bytes) -> None:
        with self._lock:
            self._cache[key] = pdf
            self._cache.move_to_end(key)
            if len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

    def _get_or_render_pdf(self, theme: str, cv_json: dict) -> bytes:
        key = self._cache_key(theme, cv_json)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        html = render_html(cv_json, self.themes[theme].CSS)
        pdf = _generate_pdf_sync(html)

        self._cache_put(key, pdf)
        return pdf

    def generate_cv_pdf(self, theme: str, cv_json: dict | None = None) -> bytes:
        if theme not in self.themes:
            raise ThemeNotFoundError(theme)
        return self._get_or_render_pdf(theme, cv_json or self.cv_data)

    async def generate_cv_pdf_async(
        self, theme: str, cv_json: dict | None = None
    ) -> bytes:
        if theme not in self.themes:
            raise ThemeNotFoundError(theme)

        cv_json = cv_json or self.cv_data
        key = self._cache_key(theme, cv_json)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        html = render_html(cv_json, self.themes[theme].CSS)
        loop = asyncio.get_running_loop()
        pdf = await loop.run_in_executor(self._executor, _generate_pdf_sync, html)

        self._cache_put(key, pdf)
        return pdf
