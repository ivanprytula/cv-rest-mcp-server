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

**Decision.** Exemption checks (`peer_is_loopback`) read only `scope["client"]`,
never headers.

**Consequences.** Local development is unlimited by default; header spoofing is
ineffective. *Corrected by ADR-012:* the original assumption that "behind Cloud
Run the peer is never loopback" was false — Cloud Run's sandbox proxy presents
`127.0.0.1` as the peer for every request.

## ADR-012: TRUST_PROXY gates loopback exemptions for proxied deployments

**Context.** On fully-managed Cloud Run every inbound connection arrives through
the sandbox proxy, so the socket peer is `127.0.0.1` for all clients. The
socket-peer-only exemptions from ADR-011 therefore silently disarmed REST/MCP
rate limits and failban in production.

**Decision.** `TRUST_PROXY` setting (default `false`). When set, all loopback
exemptions are disabled: `_exempt_loopback` returns false, failban skips neither
registration nor loopback keys, so limits and bans apply to everyone as keyed
by the client-IP strategy (`CLIENT_IP_XFF_ENTRY=2` on Cloud Run). Exemption
stays on by default for direct-peer local development.

**Consequences.** One explicit knob per environment; no header-spoof surface.
Forgetting to set it on a proxied platform re-arms the silent bypass — called
out in `.env.example` and the deploy checklist.

## ADR-013: CV content delivered from GCS; image ships placeholder only

**Context.** Baking `cv.json` into the container image couples content changes
to redeploys and puts personal data inside build artifacts. A SQL database was
considered for content management but rejected: the data model is a single
validated JSON document with no relational needs (see roadmap discussion).

**Decision.** The CV document lives in a private GCS object
(`CV_DATA_GCS_URI`). `CvSource` loads it at boot, validates against `CVData`,
and hot-reloads when the object's generation changes (checked every
`CV_REFRESH_SECONDS`) — publishing an update is `gcloud storage cp` /
`just upload-cv`, no redeploy. If the object is absent or invalid at boot,
the service starts anyway on the baked-in `data/cv.example.json` placeholder
and keeps polling; `/health` reports `"cv_source": "gcs" | "file" |
"placeholder"`. Runtime refresh failures keep the last good payload.

**Consequences.** Personal CV data never enters images or build sources
(`.dockerignore` / `.gcloudignore` whitelist only the example file). The
service is never down due to missing content, but operators must watch the
`cv_source` field — serving placeholder while believing real data is live is
the failure mode. Auth for writes is delegated entirely to GCS IAM; no admin
REST surface exists. Cloud SQL remains deferred until multi-document or
multi-user requirements actually appear.

## ADR-014: MCP client snippets are static data with CI drift-checks, not live-fetched

**Context.** The landing page shows copy-pasteable MCP config snippets for
four clients (Claude Code, Codex CLI, Gemini CLI, VS Code Copilot). Formats
drift often, but vendors publish no machine-readable config API; docs sites
block CORS, and parsing prose/markdown into "the current snippet" at request
time fails silently — the worst mode for a copy-paste feature. Fetching raw
markdown from vendor GitHub repos works for only some clients (Codex and
Claude moved their references off GitHub to CORS-blocked sites).

**Decision.** Snippets live in `config/mcp_clients.json` — rendered
server-side by `routes.load_mcp_clients()` (startup aborts on a broken file)
and consumed by the same file's per-client check spec: a fetch URL plus
conservative markers that must appear in that source. A monthly GitHub Action
(`mcp-docs-drift`) runs `scripts/check_mcp_docs.py`: any missing marker opens
a tracking issue; a clean run rewrites the `verified YYYY-MM` stamps shown as
badges on the landing page and auto-commits them. No runtime fetching, no
localStorage caching.

**Consequences.** The page stays zero-runtime-dependency and fails loudly at
deploy time on bad data instead of serving guessed configs; freshness is
eventual (up to a month) but human-confirmed via the issue queue. Marker sets
are intentionally loose enough to survive doc prose edits while still
catching format changes; first-line maintenance when an issue fires is
updating one JSON entry.
