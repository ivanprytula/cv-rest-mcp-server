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

**SPA deployment (spa-origin)**: React SPA builds to `frontend/dist/`, then packaged in a separate container (`Dockerfile.spa`) served by nginx on Cloud Run at `app.<apex>`. CI/CD workflow (`.github/workflows/ci-cd.yaml`) builds both `api-core` and `spa-origin` images, then deploys both services to Cloud Run. Static assets are hashed by Vite (long cache lifetime). See `terraform.tfvars.example` for static_assets config (optional Cloud CDN prefix-routing).

**CI/CD strategy**: `.github/workflows/ci-cd.yaml` is self-contained — all build and deploy logic lives there. No shell script dependency. Builds: api-core (Dockerfile), spa-origin (Dockerfile.spa), api-games (services/games/Dockerfile). Deploys: all three services to Cloud Run. IAM, secrets, and policies are managed by Terraform.

**Manual image builds** (first-time bootstrap or CI/CD unavailable): Use `just build-images <gcp-project>` to build and push all three images to GCR in parallel. Then `terraform apply` to deploy.

## Bootstrap & Deployment

**First-time setup (one operator, one time, in order):**

```bash
# STEP 1: Enable APIs, create CV bucket, grant runtime SA read access
export GCP_PROJECT=<your-project>
just deploy bootstrap

# STEP 2: Create versioned Terraform state bucket + init backend
just deploy bootstrap-state

# STEP 3: Create Secret Manager secrets (JWT signing key, refresh token pepper)
just deploy bootstrap-secrets

# STEP 4: Deploy infrastructure via Terraform
# Edit terraform/terraform.tfvars with your values (apex domain, WIF config, etc.)
cd terraform && terraform plan
terraform apply

# STEP 5: Upload CV data to GCS
just deploy upload-cv

# STEP 6: Verify deployment (optional, manual health check)
just deploy verify
```

**After bootstrap:** CI/CD (`terraform apply` for changes + `.github/workflows/ci-cd.yaml` for pushes to main) handles all further deployments. Manual steps are idempotent — re-running them is safe.

**Removed from script:** `build`, `deploy`, `wif` stages. These are now:

- `build` / `deploy` — handled by CI/CD workflow
- `wif` — handled by Terraform module `github_wif`

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
