# Decisions

## ADR-001: Remove module-level `CV_DATA` singleton

**Context.** `app/cv_data.py` exported a module-level `CV_DATA` instance loaded at
import time. This made tests brittle (global mutation) and hid the file path.

**Decision.** Replace with `load_cv_data(path: Path) -> CVData`. `PdfService` owns
the loaded instance.

**Consequences.** Every consumer must pass or inject a path. Tests construct the
service explicitly.

## ADR-002: Introduce `PdfService`

**Context.** PDF generation was a pair of bare functions using module-level cache
and executor.

**Decision.** Encapsulate cache, executor, loaded CV data, and theme registry in a
`PdfService` class. Provide `generate_cv_pdf`, `generate_cv_pdf_async`,
`list_themes`, and `clear_cache`.

**Consequences.** Single ownership of state; thread-safe via `threading.Lock`;
easy to mock or replace in tests.

## ADR-003: Fix deprecated asyncio API

**Context.** `asyncio.get_event_loop()` is deprecated in Python 3.12+.

**Decision.** Use `asyncio.get_running_loop()` in the async generation path.

**Consequences.** No behavioral change; future-proof for 3.16 removal.

## ADR-004: MCP tools bypass FastAPI `Depends`

**Context.** FastMCP's `@mcp.tool` decorator breaks when tool functions use
FastAPI `Depends` (Pydantic schema generation error).

**Decision.** MCP tools read `app.state.pdf_service` directly. A `None` guard
raises `RuntimeError` if lifespan has not yet run.

**Consequences.** Tight coupling to `app.state`, but avoids a FastMCP limitation.
Revisit if FastMCP adds `Depends` support.

## ADR-005: Remove reload / file-watcher feature

**Context.** A reload endpoint, token auth, and optional file watcher were
implemented to hot-reload `cv.json` without restarting.

**Decision.** Roll back all reload-related code. Restarting is acceptable for a
single-file CV; the feature added configuration surface without proportional value.

**Consequences.** Simpler lifespan, fewer settings, smaller attack surface.

## ADR-006: Remove `THEME_NAME` from theme modules

**Context.** Each theme module defined a `THEME_NAME` string constant that was
never used by the rendering pipeline.

**Decision.** Delete the constant. Theme names are derived from module names
(`classic`, `minimal`, `modern`).

**Consequences.** Less duplication; theme contract is now just `CSS: str`.

## ADR-007: Extract `Depends(get_pdf_service)` to module-level

**Context.** `ruff` rule `B008` rejects `Depends(...)` calls inside function
default arguments.

**Decision.** Create `get_pdf_service_dep = Depends(get_pdf_service)` at module
scope in `app/routes.py` and reference it in signatures.

**Consequences.** Lint passes; semantics are unchanged.
