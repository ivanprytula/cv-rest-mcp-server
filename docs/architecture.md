# Architecture

FastAPI + FastMCP service that renders a CV as JSON or themed PDFs. All PDF generation
happens in a thread pool; the async path delegates to it via `asyncio.get_running_loop()`.

## Components

| Module                 | Responsibility                                                               |
| ---------------------- | ---------------------------------------------------------------------------- |
| `app/main.py`          | FastAPI app, CORS, rate-limit middleware, MCP + `/static` mounts, lifespan   |
| `app/routes.py`        | REST endpoints (`/`, `/health`, `/cv`, `/cv/html`, `/cv/preview`, `/cv/pdf`) |
| `app/pdf_generator.py` | `PdfService` class: cache, thread pool, sync/async PDF generation            |
| `app/renderer.py`      | Jinja2 HTML rendering via `templates/cv_base.html`                           |
| `app/cv_data.py`       | Pydantic models + `load_cv_data(path)` entry point                           |
| `app/themes/`          | Theme modules exposing `CSS: str`                                            |
| `app/rate_limiter.py`  | slowapi `Limiter` instance                                                   |
| `app/settings.py`      | `cv_data_path`, `port`                                                       |

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

Per-IP, in-memory. `localhost` is exempt.

| Endpoint      | Limit   |
| ------------- | ------- |
| `/`           | 30/min  |
| `/health`     | 60/min  |
| `/cv`         | 30/min  |
| `/cv/html`    | 30/min  |
| `/cv/preview` | 30/min  |
| `/cv/pdf`     | 5/15min |
