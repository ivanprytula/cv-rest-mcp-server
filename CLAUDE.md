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
- `terraform/modules/iam_secrets/` — service accounts, IAM bindings, Artifact Registry repo
- `.github/workflows/` — `ci-cd.yml` (infra) and `deploy-app.yml` (app), path-filtered

## Non-Obvious Patterns

**CSS build sync**: `static/css/site.css` is a committed Tailwind build artifact. Must be rebuilt and committed when template classes change. Pre-commit hooks do NOT run `npm run css` — you must do it manually. See [AGENTS.md](AGENTS.md#css-build-sync).

**Auth testing**: Tests use isolated in-memory SQLite repos per test. Local dev seeding reads `FIRST_ADMIN_*` env vars. Swagger UI runs on `/docs` with optional contact metadata from `CONTACT_NAME` / `CONTACT_EMAIL` (injected by `just dev` via `.env`).

**Lifecycle separation**: Engine init/schema/teardown moved from `UserService` to app lifespan in `main.py` (commit 0c6d30b). Business logic stays in service; infrastructure stays in the boundary.

**Middleware order**: Runs outside-in. SecurityHeaders first (outermost), then Guard, CredentialedCORS, JWTAuth (innermost). See [app/main.py:166-188](app/main.py#L166-L188).

**SPA deployment (spa-origin)**: React SPA builds to `frontend/dist/`, then packaged in a separate container (`frontend/Dockerfile`) served by nginx on Cloud Run at `app.<apex>`. Static assets are hashed by Vite (long cache lifetime). See `terraform.tfvars.example` for static_assets config (optional Cloud CDN prefix-routing).

**CI/CD strategy**: Two path-filtered workflows enforce the boundary "Terraform owns the platform; the app pipeline owns the released artifact."

- `.github/workflows/deploy-app.yml` — triggers on `app/**`, `frontend/**`, `services/**`, Dockerfiles. Lint + tests → builds api-core (Dockerfile), api-games (services/games/Dockerfile), spa-origin (frontend/Dockerfile) → `gcloud run deploy` per service → verify. Never touches Terraform state.
- `.github/workflows/ci-cd.yml` — triggers on `terraform/**`. tflint + checkov → Infracost budget check → `terraform plan` (posted to the PR, uploaded as an artifact) → `terraform apply` of that exact reviewed plan, gated on the `dev` GitHub Environment's required reviewer.

**Image field ownership**: `modules/cloud_run_service` sets `lifecycle { ignore_changes = [template[0].containers[0].image] }`. Terraform owns the service's shape (scaling, env vars, secrets, ingress); `gcloud run deploy` owns which image tag is live. Without this the two tools revert each other. `var.image_overrides` is now break-glass only — routine releases don't go through Terraform.

**Manual image builds** (first-time bootstrap or CI/CD unavailable): Use `just build-images <gcp-project>` to build and push all three images to the `cv-images` Artifact Registry repo (`<region>-docker.pkg.dev/<project>/cv-images/<service>`) in parallel. Then `terraform apply` to deploy.

**Deployer service account**: CI authenticates via WIF as `deployer@<project>.iam.gserviceaccount.com`, created and granted by `modules/iam_secrets`. The `GCP_DEPLOY_SA` GitHub secret MUST match it — a stale value pointing at another SA fails in a confusing way: `gcloud builds submit` and `services describe` succeed while every IAM-dependent call 403s. Legacy `cv-rest-mcp-server-deployer@` / `cv-ivanprytula-deployer@` SAs predate the Terraform module and are unmanaged.

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

**After bootstrap:** the two workflows handle all further deployments — `ci-cd.yml` for `terraform/**` changes, `deploy-app.yml` for application code. Manual steps are idempotent — re-running them is safe.

**Removed from script:** `build`, `deploy`, `wif` stages. These are now:

- `build` / `deploy` — handled by `deploy-app.yml`
- `wif` — handled by Terraform module `github_wif`

**Also owned by Terraform, not the script:** runtime/deployer service accounts and the `cv-images` Artifact Registry repo (`modules/iam_secrets`), and every API except `cloudresourcemanager` (`modules/gcp_apis`). The script's `bootstrap` only enables `cloudresourcemanager` (chicken-and-egg: Terraform's own `google_project_service` resources need it first), creates the CV data bucket, and grants Cloud Build IAM. Secret *containers and versions* stay script-owned (`bootstrap-secrets`) so key material never enters `.tfvars` or Terraform state; Terraform only binds `secretAccessor` to an existing secret ID.

## Cost Estimation

Infracost estimates GCP monthly costs before `terraform apply`. Budget: **$100/month**.

```bash
# Local estimate (requires Infracost CLI installed)
infracost breakdown --path terraform/

# Pre-commit hook runs automatically (warns if cost trending high)
# CI/CD: posts cost estimate on every PR, fails if > $100
```

**Setup**: Set `INFRACOST_API_KEY` as a GitHub repository secret to enable CI/CD cost estimates.

## Testing

```bash
uv run pytest               # Full suite (405 tests)
uv run pytest -x            # Stop on first failure
uv run pytest --cov         # Coverage report (96% target)
uv run pytest tests/test_e2e.py -xvs  # E2E with login flow
```

Auth tests use fixture `user_service` (conftest.py:240) with seeded operator/correct-password. Routes reach it via monkeypatch.

## Code Style

Full conventions live in [AGENTS.md](AGENTS.md#code-style). The rules most often
tripped over:

- Python 3.14 — no newer syntax. Dependencies via `uv add`, never `pip` or `uv pip`.
- Type-hint public functions/methods (incl. return types); Google-style docstrings.
- `pathlib`, not `os.path`. F-strings, not `.format()`/`%`. EAFP over pre-checks.
- Validate request bodies with Pydantic models.

Follow [ACROSS design principles](https://github.com/your-org/cv-rest-mcp-server/blob/main/ACROSS.md):

- Composition over inheritance (no single-impl ABCs)
- Lifecycle separation (DI/factory separate from business logic)
- Domain-centric naming (`authenticate()`, not `process_login()`)
- Minimize abstractions (YAGNI)

Ruff + type checking enforced pre-commit. Run locally: `just code-quality`.

## Markdown Style

Always tag fenced code blocks with a language — never a bare ` ``` `. Use `text`
for plain output, ASCII diagrams, and command output; `bash`, `python`, `hcl`,
`yaml`, `json`, `mermaid` where they apply. Surround lists and fences with blank
lines. See [AGENTS.md](AGENTS.md#markdown-style).

## Paired Docs (public repo — read before editing infra docs)

Two infra docs exist in two versions. The `.agent/` copies hold **real** values
and are gitignored; the `docs/` copies use `<PLACEHOLDERS>` and are public.

| Local (real) | Committed (sanitised) |
| --- | --- |
| `.agent/infrastructure_local.md` | `docs/infrastructure.md` |
| `.agent/architecture-diagrams_local.md` | `docs/architecture-diagrams.md` |

**Update both in the same change** whenever a concrete value appears or changes
— project id/number, IP, hostname, DNS zone, bucket, service-account email, WIF
path, Artifact Registry path, port, image tag scheme. This includes values
produced by `terraform apply`, `gcloud` resource creation, or new GitHub
secrets/variables, not just direct edits to the files.

Never commit a real project number, service-account email, state bucket name, or
WIF provider path. See [AGENTS.md](AGENTS.md#paired-documentation).

## Git Workflow

Branch from `main` as `feature/<name>` — never commit directly to `main`.
Conventional Commits. Stage changes for review; do not commit or push unless
asked. No `Co-Authored-By:` or tool-attribution lines. See
[AGENTS.md](AGENTS.md#git-workflow).

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
