# Design

## Principles

- **No module-level singletons.** `CVData` is loaded explicitly via `load_cv_data(path)`
  and owned by `PdfService`. This avoids import-order bugs and makes testing easier.
- **Thread-safe by default.** `PdfService` protects its cache with a `threading.Lock`
  and runs WeasyPrint in a bounded `ThreadPoolExecutor`.
- **Explicit async boundary.** The async API (`generate_cv_pdf_async`) delegates to
  the sync API via `loop.run_in_executor`; there is no bare `asyncio.get_event_loop()`.
- **Theme contract.** Every theme module exposes `CSS: str`. Discovery happens at
  import time; no registry or `THEME_NAME` constant required.
- **Structure vs. styling split.** The shared template (`cv_base.html`) owns markup
  structure and geometry: page setup, list markup (`ul.skill-list`, `ul.highlights`),
  and fallback styles emitted as zero-specificity `:where()` rules so any theme can
  override them with ordinary selectors regardless of stylesheet order. Themes only
  vary typography (font family/size) and colors — no absolute positioning, z-index,
  or padding hacks.

## Key Patterns

- **Dependency injection.** Routes declare `pdf_service = get_pdf_service_dep`.
  The dependency reads `app.state.pdf_service`, which is created in lifespan.
- **MCP workaround.** FastMCP tools cannot use FastAPI `Depends`, so they access
  `app.state` directly after a `None` guard.
- **LRU cache.** `OrderedDict` bounded to 50 entries. Keys are `(theme, sha256)`.
  Invalidation is manual via `PdfService.clear_cache()`. Cache probes never hold
  the lock during rendering — both sync and async paths probe → render → insert.
- **Layered access control.** `GuardMiddleware` answers "may this address talk to
  us at all" (allowlist/blocklist/bans/hours) before any work; the slowapi limiter
  answers "how often may this client act". Bans are recorded from both REST 429s
  and MCP `ToolError`s, and loopback socket peers are always exempt (never
  header-derived IPs, which are attacker-controllable).
- **MCP rate limiting via request-context stubs.** Module-level functions
  decorated with slowapi's limiter are invoked with the request obtained from
  `fastmcp.server.dependencies.get_http_request()`; outside HTTP contexts
  (tests, in-memory transport) enforcement is a no-op.

## Constraints

- Python 3.14+
- Stateless between requests (except in-memory caches: PDF LRU, rate-limit
  buckets, dynamic bans — all single-process)
- Cloud Run-compatible: reads `PORT`, shuts down executor on lifespan exit;
  set `CLIENT_IP_XFF_ENTRY=2` behind the GFE for real client IPs
- No secrets in repo; runtime knobs are documented in `.env.example`

## Testing

- pytest + `httpx.AsyncClient` + `ASGITransport`
- `asyncio_mode = "auto"`
- `PdfService` is instantiated directly in tests; `app.state` is overridden where needed
- Guard policies are tested by calling `GuardMiddleware` directly with synthetic
  ASGI scopes; MCP limits use fake non-loopback requests patched into
  `get_http_request`
