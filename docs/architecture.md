# Architecture

FastAPI + FastMCP service that renders a CV as JSON or themed PDFs. All PDF generation
happens in a thread pool; the async path delegates to it via `asyncio.get_running_loop()`.

## Components

| Module                   | Responsibility                                                               |
| ------------------------ | ---------------------------------------------------------------------------- |
| `app/main.py`            | FastAPI app, middleware stack, MCP tools + `/static` mount, lifespan         |
| `app/routes.py`          | REST endpoints (`/`, `/health`, `/cv`, `/cv/html`, `/cv/preview`, `/cv/pdf`) |
| `app/pdf_generator.py`   | `PdfService` class: cache, thread pool, sync/async PDF generation            |
| `app/renderer.py`        | Jinja2 HTML rendering via `templates/cv_base.html`                           |
| `app/cv_data.py`         | Pydantic models + `load_cv_data(path)` entry point                           |
| `app/themes/`            | Theme modules exposing `CSS: str`                                            |
| `app/rate_limiter.py`    | slowapi `Limiter`, client-IP resolution, stacked-limit decorator             |
| `app/mcp_limits.py`      | Rate limits enforced inside MCP tools (slowapi stubs + request context)       |
| `app/guard_middleware.py`| Outermost access gate: allowlist/blocklist/bans/service hours                |
| `app/ip_lists.py`        | IP/CIDR parsing and membership checks                                        |
| `app/service_hours.py`   | Scheduled availability window evaluation                                     |
| `app/failban.py`         | Dynamic ban tracker (fail2ban-lite) fed by rate-limit violations             |
| `app/settings.py`        | All runtime config (see `.env.example`)                                       |

## Data Flow

1. Request hits FastAPI router.
2. Route injects `PdfService` via `Depends(get_pdf_service)`.
3. For PDFs, `PdfService.generate_cv_pdf_async()` checks an LRU cache keyed by
   `(theme, sha256(cv_json))`.
4. On miss, it submits sync WeasyPrint work to a `ThreadPoolExecutor`.
5. Rendered PDF bytes are returned; sync path used by MCP tools, async path by REST.
6. `/cv/html` skips PDF generation entirely — it renders the same
   `templates/cv_base.html` + theme CSS straight to an HTML response.
   `/cv/preview` wraps that endpoint in an iframe inside a toolbar page
   (`templates/preview.html`) so users can inspect a theme before downloading.

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
and feed the dynamic ban tracker.

## Access Control

`GuardMiddleware` (`app/guard_middleware.py`) is added last so it runs first,
before CORS and rate limiting. Pure ASGI; rejects before any handler work.
Evaluation order: allowlist (`ALLOWED_IPS`) → blocklist (`BLOCKED_IPS`) →
dynamic bans (`FAILBAN_*`) → service hours (`SERVICE_HOURS_*`). Each list may
be inline (comma-separated) or file-based (`BLOCKED_IPS_FILE` /
`ALLOWED_IPS_FILE`, one CIDR per line, `#` comments); inline and file contents merge, and a configured but
unreadable file aborts startup. `/health` always passes; with no policy
configured the middleware short-circuits to passthrough.

MCP tools enforce their own limits inside the tool body via FastMCP's request
context — the mounted `/mcp` sub-app is invisible to route-level middleware
decorators.
