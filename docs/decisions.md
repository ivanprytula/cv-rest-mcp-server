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

## ADR-008: Rate-limit MCP tools via slowapi stubs + request context

**Context.** The mounted `/mcp` sub-app is invisible to route decorators and
`SlowAPIMiddleware`, so MCP PDF renders were unthrottled. FastMCP tools cannot
use FastAPI `Depends`.

**Decision.** Module-level stub functions decorated with the shared `limiter`
are called inside each tool with the request from
`fastmcp.server.dependencies.get_http_request()`. No HTTP context (tests,
in-memory transport) → enforcement no-ops. `RateLimitExceeded` becomes
`ToolError("Rate limit exceeded")`. The PDF tool is async and routes through
the bounded executor.

**Consequences.** One limiter instance governs both surfaces; no new
dependencies; relies on slowapi's decorator wrapper accepting an explicit
`Request` argument (stable, documented behavior).

## ADR-009: Client-IP resolution strategy for rate limiting

**Context.** Behind Cloud Run's GFE the socket peer is a shared Google IP —
per-IP buckets would lump all visitors together (self-DoS). GFE *appends* to
`X-Forwarded-For` rather than overwriting it, so standard ProxyFix math does
not apply.

**Decision.** `get_client_ip()` uses configurable strategies in order:
Nth XFF entry from the right (`CLIENT_IP_XFF_ENTRY`; Cloud Run recipe: `2`,
the penultimate entry = real client, un-spoofable without controlling a hop
adjacent to GFE), then a raw trusted header (`CLIENT_IP_HEADER`, nginx
`X-Real-IP` case), then the socket peer.

**Consequences.** Per-client fairness works behind proxies. The raw-header
mode is spoofable if the app is reachable without that proxy — document
deployment assumptions. IP rotation remains possible; sustained caps and the
bounded executor bound total damage regardless of keying.

## ADR-010: GuardMiddleware for static lists, hours, dynamic bans

**Context.** Allowlist/blocklist, scheduled availability windows, and
fail2ban-style temporary bans are "may this client talk to us at all"
policies, distinct from per-client throughput limits. They should reject
before CORS/rate-limiting run and never consume rate slots.

**Decision.** Pure-ASGI `GuardMiddleware` added last (executes first):
allowlist → blocklist → dynamic ban → service hours. Bans are recorded from
both REST 429s and MCP `ToolError`s into an in-memory, thread-safe,
memory-capped tracker. All policies are env-configured and disabled by
default; with none configured the middleware short-circuits to passthrough.
`/health` always passes so monitoring survives any policy.

**Consequences.** In-memory state is single-process (matches slowapi storage);
restart clears bans. Static blocklist intentionally has no loopback exemption
(operator-explicit config), while dynamic bans never ban loopback.

## ADR-011: Loopback exemptions use socket peer only

**Context.** Dev traffic (localhost) must bypass rate limits and bans, but
header-derived IPs (XFF entries, `CLIENT_IP_HEADER`) are attacker-controllable
behind a proxy — exempting on them would let anyone claim a loopback identity
and bypass everything.

**Decision.** Exemption checks (`peer_is_loopback`) read only `scope["client"]`.
Behind Cloud Run the peer is never loopback, so exemptions cannot trigger in
production by construction.

**Consequences.** Local development is unlimited by default; production
behavior is unaffected regardless of header spoofing.
