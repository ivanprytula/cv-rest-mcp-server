# Architecture

FastAPI + FastMCP service that renders a CV as JSON or themed PDFs. Browser styling is
compiled from the templates into `static/css/site.css` during the build; production
serves that committed asset without a third-party CDN. All PDF generation happens in
a bounded thread pool.

## Components

| Module | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app, middleware stack, MCP tools + `/static` mount, lifespan |
| `app/routes.py` | REST endpoints (`/`, `/health`, `/cv`, `/cv/html`, `/cv/preview`, `/cv/pdf`, `/cv/tailor`, games) — see `docs/api.md` for the contract |
| `app/pdf_generator.py` | `PdfService` class: cache, thread pool, sync/async PDF generation |
| `app/renderer.py` | Jinja2 HTML rendering via `templates/cv_base.html` |
| `app/cv_data.py` | Pydantic models + `validate_cv_payload` / `load_cv_data(path)` |
| `app/cv_source.py` | CV document resolution: local file or GCS object, hot reload, placeholder fallback |
| `app/themes/` | Theme modules exposing `CSS: str` |
| `app/rate_limiter.py` | slowapi `Limiter`, client-IP resolution, stacked-limit decorator |
| `app/mcp_limits.py` | Rate limits enforced inside MCP tools (slowapi stubs + request context) |
| `app/guard_middleware.py` | Outermost access gate: allowlist/blocklist/bans/service hours |
| `app/ip_lists.py` | IP/CIDR parsing and membership checks |
| `app/service_hours.py` | Scheduled availability window evaluation |
| `app/failban.py` | Dynamic ban tracker (fail2ban-lite) fed by rate-limit violations |
| `app/settings.py` | All runtime config (see `.env.example`) |
| `static/css/` | Vendored Tailwind input and generated browser stylesheet |

## Data Flow

1. `CvSource` (`app/cv_source.py`) resolves the CV document: a private GCS
   object (`CV_DATA_GCS_URI`, re-checked every `CV_REFRESH_SECONDS` via the
   object generation) or a local file. If neither is available yet, it serves
   the baked-in `data/cv.example.json` placeholder and keeps polling —
   uploading a real cv.json goes live without a redeploy.
2. Request hits FastAPI router.
3. Route injects `PdfService` via `Depends(get_pdf_service)`; `pdf_service.cv_data`
   reads through `CvSource`.
4. For PDFs, `PdfService.generate_cv_pdf_async()` checks an LRU cache keyed by
   `(theme, sha256(cv_json))`.
5. On miss, it submits sync WeasyPrint work to a `ThreadPoolExecutor`.
6. Rendered PDF bytes are returned; sync path used by MCP tools, async path by REST.
7. `/cv/html` skips PDF generation entirely — it renders the same
   `templates/cv_base.html` + theme CSS straight to an HTML response.
   `/cv/preview` wraps that endpoint in an iframe inside a toolbar page
   (`templates/preview.html`) so users can inspect a theme before downloading.

`GET /health` reports which payload is live: `"cv_source": "gcs" | "file" |
"placeholder"`.

Tailwind CSS is built with the pinned npm dependency using `just css` and scanned
against `templates/**/*.html`. CI regenerates the stylesheet and fails if the
committed output is stale; the production image only needs the generated static file.

The renderer builds a context from the CV mapping while excluding its reserved
`css`, `consent_enabled`, and `consent_company` keys. It then applies those
renderer-owned values explicitly, so arbitrary extra CV metadata remains
available without allowing payload collisions to override rendering controls.
Browser pages use only the committed `static/css/site.css`; static assets are
served by FastAPI and are not fetched from a CDN or loaded by the PDF renderer.
WeasyPrint receives a deny-all URL fetcher, so PDF generation rejects local files,
HTTP(S), `data:` URLs, and every other external URL.

## MCP

Mounted at `/mcp` via Streamable HTTP. Tools (`get_cv`, `get_available_themes`,
`generate_cv_pdf`) read `app.state.pdf_service` directly because FastMCP's
`@mcp.tool` decorator does not support FastAPI `Depends`.

## Rate Limiting

slowapi `Limiter` keyed by `get_client_ip()` (`app/rate_limiter.py`): the resolved
client IP follows `CLIENT_IP_XFF_ENTRY` (Nth X-Forwarded-For entry from the right),
then `CLIENT_IP_HEADER`, then the socket peer. **Loopback socket peers are exempt**
from all limits and dynamic bans (dev convenience; header-derived IPs are ignored
for exemption because they are attacker-controllable).

Limits are stacked (burst + sustained) via the `@limits(...)` decorator, so every
limit for an endpoint is evaluated in a single slowapi pass:

| Endpoint / tool                  | Burst       | Sustained  |
| -------------------------------- | ----------- | ---------- |
| `/`                              | 30/min      | 120/hour   |
| `/health`                        | 60/min      | —          |
| `/cv`, `/cv/html`, `/cv/preview` | 30/min      | 300/hour   |
| `/cv/pdf`                        | 5/15min     | 15/hour    |
| MCP read tools                   | 30/min      | 240/hour   |
| MCP `generate_cv_pdf_tool`       | 5/15min     | 15/hour    |

REST breaches return 429; MCP breaches surface as `ToolError("Rate limit exceeded")`
and feed the dynamic ban tracker. Loopback *socket peers* are exempt from
limits and bans by default (local dev); `TRUST_PROXY=true` disables those
exemptions for proxied platforms where every peer appears as 127.0.0.1
(Cloud Run) — required there alongside a client-IP strategy such as
`CLIENT_IP_XFF_ENTRY=2`.

## Access Control

`GuardMiddleware` (`app/guard_middleware.py`) and `SecurityHeadersMiddleware`
are added last so they run first, before CORS and rate limiting; every response
carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and
`Referrer-Policy: strict-origin-when-cross-origin`. CORS is public-read:
wildcard origin, no credentials. Pure-ASGI guard rejects before any handler
work.
Evaluation order: allowlist (`ALLOWED_IPS`) → blocklist (`BLOCKED_IPS`) →
dynamic bans (`FAILBAN_*`) → service hours (`SERVICE_HOURS_*`). Each list may
be inline (comma-separated) or file-based (`BLOCKED_IPS_FILE` /
`ALLOWED_IPS_FILE`, one CIDR per line, `#` comments); inline and file contents merge, and a configured but
unreadable file aborts startup. `/health` always passes; with no policy
configured the middleware short-circuits to passthrough.

MCP tools enforce their own limits inside the tool body via FastMCP's request
context — the mounted `/mcp` sub-app is invisible to route-level middleware
decorators.
