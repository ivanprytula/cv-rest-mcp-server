import asyncio
import hashlib
import importlib
import json
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from types import ModuleType
from typing import NoReturn

from fastapi import HTTPException
from weasyprint import HTML

from services.portfolio.constants import (
    PDF_CACHE_MAX_ENTRIES,
    PDF_EXECUTOR_MAX_WORKERS,
    THEMES_DIR,
)
from services.portfolio.cv_data import validate_cv_payload
from services.portfolio.documents.document_row import KIND_CV
from services.portfolio.documents.document_service import DocumentService
from services.portfolio.renderer import render_html
from services.portfolio.settings import settings
from services.portfolio.tenancy import TenantId


class _URLFetchDeniedError(Exception):
    pass


def _deny_all_url_fetcher(url: str) -> NoReturn:
    raise _URLFetchDeniedError(f"URL fetching is disabled: {url}")


def load_themes() -> dict[str, ModuleType]:
    """Load all theme modules from the themes directory.

    Each module must export a `CSS: str` stylesheet string. "original" is
    the flagship look and is always listed first; remaining themes are
    ordered alphabetically for determinism.
    """
    discovered: dict[str, ModuleType] = {}
    for path in THEMES_DIR.iterdir():
        if path.suffix == ".py" and path.name != "__init__.py":
            module_name = path.stem
            try:
                module = importlib.import_module(
                    f"services.portfolio.themes.{module_name}"
                )
                if not hasattr(module, "CSS"):
                    raise TypeError(
                        f"Theme '{module_name}' is missing required 'CSS: str' attribute"
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
        return HTML(string=html, url_fetcher=_deny_all_url_fetcher).write_pdf()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PDF generation failed") from exc


def _consent_tag(consent: bool, consent_company: str) -> str:
    """Normalized cache-key suffix distinguishing consent variants."""
    if not consent:
        return ""
    company = " ".join(consent_company.split()).lower()
    return f"|consent:{company}"


class ThemeNotFoundError(HTTPException):
    def __init__(self, theme: str) -> None:
        super().__init__(status_code=404, detail=f"Theme '{theme}' not found")


class PdfService:
    def __init__(
        self,
        documents: DocumentService,
        tenant_id: TenantId,
        *,
        max_entries: int = PDF_CACHE_MAX_ENTRIES,
        max_workers: int = PDF_EXECUTOR_MAX_WORKERS,
    ) -> None:
        self._documents = documents
        self._tenant_id = tenant_id
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.themes: dict[str, ModuleType] = load_themes()
        self._cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._inflight: dict[tuple[str, str], Future[bytes]] = {}

    async def cv_data(self) -> dict:
        """Current CV document: the operator's DB row, else the shipped file.

        Normalized through `validate_cv_payload` the same way a file read
        always was — a DB row or fallback file missing an optional list
        field (e.g. `projects`) still renders with `[]`, not a KeyError.
        """
        payload = await self._documents.read(
            KIND_CV, tenant_id=self._tenant_id, fallback_path=settings.cv_data_path
        )
        if payload is None:
            return {}
        return validate_cv_payload(payload)

    async def cv_source_kind(self) -> str:
        """Where the served CV came from: "database", "file", or "unavailable"."""
        payload = await self._documents.read(
            KIND_CV, tenant_id=self._tenant_id, fallback_path=None
        )
        if payload is not None:
            return "database"
        payload = await self._documents.read(
            KIND_CV, tenant_id=self._tenant_id, fallback_path=settings.cv_data_path
        )
        return "file" if payload is not None else "unavailable"

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def list_themes(self) -> list[str]:
        return list(self.themes.keys())

    def _cache_key(
        self, theme: str, cv_json: dict, consent_tag: str = ""
    ) -> tuple[str, str]:
        payload = json.dumps(cv_json, sort_keys=True) + consent_tag
        cv_hash = hashlib.sha256(payload.encode()).hexdigest()
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

    def _render_pdf(
        self,
        key: tuple[str, str],
        theme: str,
        cv_json: dict,
        *,
        consent: bool,
        consent_company: str,
    ) -> bytes:
        html = render_html(
            cv_json,
            self.themes[theme].CSS,
            consent=consent,
            consent_company=consent_company,
        )
        pdf = _generate_pdf_sync(html)
        self._cache_put(key, pdf)
        return pdf

    def _get_or_render_pdf(
        self,
        theme: str,
        cv_json: dict,
        *,
        consent: bool = False,
        consent_company: str = "",
    ) -> bytes:
        tag = _consent_tag(consent, consent_company)
        key = self._cache_key(theme, cv_json, tag)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        return self._render_pdf(
            key, theme, cv_json, consent=consent, consent_company=consent_company
        )

    def generate_cv_pdf(
        self,
        theme: str,
        cv_json: dict,
        *,
        consent: bool = False,
        consent_company: str = "",
    ) -> bytes:
        """Render synchronously. Callers must supply `cv_json` — fetching the
        current CV is async (`cv_data()`); this method does not do it for you.
        """
        if theme not in self.themes:
            raise ThemeNotFoundError(theme)
        return self._get_or_render_pdf(
            theme,
            cv_json,
            consent=consent,
            consent_company=consent_company,
        )

    async def generate_cv_pdf_async(
        self,
        theme: str,
        cv_json: dict | None = None,
        *,
        consent: bool = False,
        consent_company: str = "",
    ) -> bytes:
        if theme not in self.themes:
            raise ThemeNotFoundError(theme)

        cv_json = cv_json or await self.cv_data()
        tag = _consent_tag(consent, consent_company)
        key = self._cache_key(theme, cv_json, tag)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

            future = self._inflight.get(key)
            if future is None:
                future = self._executor.submit(
                    self._render_pdf,
                    key,
                    theme,
                    cv_json,
                    consent=consent,
                    consent_company=consent_company,
                )
                self._inflight[key] = future

                def remove_inflight(completed: Future[bytes]) -> None:
                    with self._lock:
                        if self._inflight.get(key) is completed:
                            del self._inflight[key]

                loop = asyncio.get_running_loop()
                future.add_done_callback(lambda f: loop.call_soon(remove_inflight, f))

        return await asyncio.shield(asyncio.wrap_future(future))
