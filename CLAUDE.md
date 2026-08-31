# CV REST/MCP Server — Claude Context

FastAPI + FastMCP service rendering CVs as JSON, HTML, themed PDFs, and MCP tools. See [AGENTS.md](AGENTS.md) for human-readable setup and [README.md](README.md) for API/feature overview.

## Quick Commands

All commands use `uv` for local development (see [AGENTS.md](AGENTS.md#python-environment)):

```bash
uv sync --group dev     # Install dependencies (first time)
uv run pytest           # Run test suite (all tests, 405 total)
uv run pytest tests/test_auth.py -k <pattern>  # Run specific auth tests
just dev                # Start dev server with hot reload (port 8080)
just code-quality       # Ruff check + format + type check
npm run css             # Rebuild Tailwind CSS (required after template changes)
```

## Project State

**Current phase**: Phase 1d — Operator SPA (React 19 + Vite + TypeScript) + JWT auth (HS256).

**Key files**:
- `app/main.py` — FastAPI app setup, middleware, lifespan
- `app/auth/user_store.py` — Async SQLAlchemy user repo (aiosqlite, Phase 2 Postgres-ready)
- `app/routes.py` — REST API endpoints (`/cv`, `/cv/html`, `/cv/pdf`)
- `frontend/` — React operator SPA + TanStack Query
- `tests/conftest.py` — Shared fixtures (auth fixtures at line 240+)

## Non-Obvious Patterns

**CSS build sync**: `static/css/site.css` is a committed Tailwind build artifact. Must be rebuilt and committed when template classes change. Pre-commit hooks do NOT run `npm run css` — you must do it manually. See [AGENTS.md](AGENTS.md#css-build-sync).

**Auth testing**: Tests use isolated in-memory SQLite repos per test. Local dev seeding reads `FIRST_ADMIN_*` env vars. Swagger UI runs on `/docs` with optional contact metadata from `CONTACT_NAME` / `CONTACT_EMAIL` (injected by `just dev` via `.env`).

**Lifecycle separation**: Engine init/schema/teardown moved from `UserService` to app lifespan in `main.py` (commit 0c6d30b). Business logic stays in service; infrastructure stays in the boundary.

**Middleware order**: Runs outside-in. SecurityHeaders first (outermost), then Guard, CredentialedCORS, JWTAuth (innermost). See [app/main.py:166-188](app/main.py#L166-L188).

## Testing

```bash
uv run pytest               # Full suite (405 tests)
uv run pytest -x            # Stop on first failure
uv run pytest --cov         # Coverage report (96% target)
uv run pytest tests/test_e2e.py -xvs  # E2E with login flow
```

Auth tests use fixture `user_service` (conftest.py:240) with seeded operator/correct-password. Routes reach it via monkeypatch.

## Code Style

Follow [ACROSS design principles](https://github.com/your-org/cv-rest-mcp-server/blob/main/ACROSS.md):
- Composition over inheritance (no single-impl ABCs)
- Lifecycle separation (DI/factory separate from business logic)
- Domain-centric naming (`authenticate()`, not `process_login()`)
- Minimize abstractions (YAGNI)

Ruff + type checking enforced pre-commit. Run locally: `just code-quality`.

## Permissions

Local `.claude/settings.local.json` allows:
- `uv run *` (any uv command)
- `just code-quality *` (linting)
- `just test *` (testing)
- Auth token curl for local testing

## Notes for Next Sessions

- Phase 2 will swap aiosqlite for asyncpg (one-line import change in `user_store.py`)
- No external LLM calls in codebase (pure FastAPI + FastMCP)
- All config via env/settings.py (12-factor)
- PDF rendering uses WeasyPrint (CPU-bound, rate-limited)
