# CV REST/MCP Server

FastAPI + FastMCP service rendering a CV as JSON, HTML, themed PDFs, and MCP tools. Operator login (Phase 1d) guards access; future phases add mutations and integrations.

## Architecture

Two services, one codebase:

| Service | Role                                               | Deployed as        |
| ------- | -------------------------------------------------- | ------------------ |
| **API** | FastAPI + FastMCP; renders CV; validates operators | `api-core` image   |
| **SPA** | React 19 + Vite; operator login & dashboard        | `spa-origin` image |

**Locally:** Both run in dev mode (API on 8080, SPA on 5173). One `just dev` command starts both with hot reload.

**Cloud Run:** Separate services. SPA nginx serves static assets (Vite-hashed); API is JSON-only. A reverse proxy (or CDN) routes `/app.domain` → SPA and `/api.domain` → API.

## Authentication

Operators sign in at `/login` with username/password. API issues an HS256 JWT token (httpOnly cookie, survives restarts). Refresh tokens stored in SQLite locally (Postgres in Phase 2).

**Unauthenticated requests:**

- `GET /` (landing page) — allowed
- `GET /health` (health check) — allowed
- `GET /cv*` (all CV endpoints) — **403 Forbidden**

See [CLAUDE.md](CLAUDE.md#authentication) for env vars (`JWT_SECRET`, `FIRST_ADMIN_USERNAME`, etc.).

## Getting Started

**Just want to see the CV locally?**

```bash
just setup && just dev
```

Open <http://localhost:8080>, log in with credentials from `.env` (`FIRST_ADMIN_USERNAME` / `FIRST_ADMIN_PASSWORD`), then browse `/revisions`.

**Want to modify the CV data?**

Edit `data/cv.json` (validated against `CVData` in `app/cv_data.py`). Restart the API server.

Set `CV_DATA_PATH` env var to point to a different JSON file. See `data/cv.example.json` for the full schema.

**Want to add operator features?**

See [AGENTS.md](AGENTS.md) for Phase 2+ roadmap (mutations, integrations, pagination).

**Ready to deploy to GCP?**

See [Deployment](#deployment) below.

## API

### REST Endpoints

Requires authentication (via login JWT).

| Method | Path                       | Description               |
| ------ | -------------------------- | ------------------------- |
| GET    | `/cv`                      | CV as JSON                |
| GET    | `/cv/html?theme=<name>`    | Rendered CV as HTML       |
| GET    | `/cv/preview?theme=<name>` | Preview page with toolbar |
| GET    | `/cv/pdf?theme=<name>`     | CV as PDF (attachment)    |

Public endpoints (no auth):

| Method | Path      | Description  |
| ------ | --------- | ------------ |
| GET    | `/`       | Landing page |
| GET    | `/health` | Health check |

Interactive OpenAPI docs (Swagger UI): [`/docs`](http://localhost:8080/docs)

### MCP Tools

Mounted at `/mcp` via HTTP JSON-RPC transport. Any MCP client (Claude Desktop, Cursor, VS Code, Windsurf) can connect:

```json
{
  "mcpServers": {
    "cv-rest-mcp-server": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

For deployed: replace `http://localhost:8080` with your public API URL.

Available tools:

| Tool                   | Parameters   | Returns                       |
| ---------------------- | ------------ | ----------------------------- |
| `get_cv`               | —            | JSON object with full CV data |
| `get_available_themes` | —            | `list[str]` of theme names    |
| `generate_cv_pdf`      | `theme: str` | Base64-encoded PDF bytes      |

## Themes

Four built-in themes: `classic`, `minimal`, `modern`, `original`. Defined in `app/themes/<name>.py` as CSS strings.

Add a new theme: create `app/themes/yourname.py` with a `CSS` constant.

## Rate Limiting

Per-IP, in-memory. `localhost` exempt.

| Endpoint  | Limit   |
| --------- | ------- |
| `/`       | 30/min  |
| `/health` | 60/min  |
| `/cv*`    | 30/min  |
| `/cv/pdf` | 5/15min |

## Development

All commands use `uv` for dependency management:

```bash
uv sync --group dev     # Install dependencies (first time)
uv run pytest           # Run tests (405 total)
uv run pytest -x        # Stop on first failure
just code-quality       # Ruff + type check
just dev                # Start both API and SPA in dev mode
npm run css             # Rebuild Tailwind (after template changes)
```

See [CLAUDE.md](CLAUDE.md#quick-commands) for full command reference.

## Docker

Build and run both services locally in a container:

```bash
just build && just run
```

Or build images manually for a GCP project:

```bash
just build-images <your-gcp-project>
```

This builds `api-core`, `spa-origin`, and any other service images and pushes them
to the `cv-images` Artifact Registry repo
(`<region>-docker.pkg.dev/<project>/cv-images/<service>`).

## Deployment

New to DNS, load balancers, or Terraform? [docs/infrastructure.md](docs/infrastructure.md)
explains how a browser request reaches your code — DNS delegation, SSL
certificates, the load balancer, Cloud Run, and how Terraform ties them
together — using this project's real resources.

### Local Development

```bash
just dev
```

Both services start with hot reload. No setup required beyond `just setup`.

### Cloud Run (GCP)

**One-time bootstrap** (idempotent):

```bash
export GCP_PROJECT=<your-gcp-project>
just deploy bootstrap          # Enable APIs, create CV bucket, set IAM
just deploy bootstrap-state    # Create Terraform state bucket
just deploy bootstrap-secrets  # Create JWT signing key + refresh token pepper
cd terraform && terraform plan && terraform apply  # Deploy all services
just deploy upload-cv          # Upload your CV data to GCS
```

See [CLAUDE.md](CLAUDE.md#bootstrap--deployment) for the full step-by-step with configuration details.

Cost Estimation (Infracost)

Before deploying, estimate monthly GCP costs:

```bash
# Local estimate (requires Infracost CLI installed)
infracost breakdown --path terraform/

# Set up CI/CD cost estimates on PRs (requires INFRACOST_API_KEY secret)
# See CLAUDE.md#cost-estimation for details
```

Budget: **$100/month**. Pre-commit hook and CI/CD automatically warn if costs trend high.

**Subsequent releases:**

Two path-filtered workflows split infrastructure from application releases —
Terraform owns the platform, `gcloud run deploy` ships the code:

| You changed | Workflow | What runs |
| --- | --- | --- |
| `app/`, `frontend/`, `services/`, Dockerfiles | `deploy-app.yml` | lint + tests → build images to Artifact Registry → `gcloud run deploy` → verify |
| `terraform/` | `ci-cd.yml` | tflint + checkov → Infracost → `terraform plan` → **approval gate** → `terraform apply` |

An app-only commit never runs Terraform, and an infra-only commit never rebuilds
images. Use `[skip deploy]` in a commit message to run checks without deploying.

Infra applies are gated on the `dev` GitHub Environment: `terraform plan` posts its
output to the PR, and the apply job waits for a required reviewer before running
the exact reviewed plan. Application rollbacks don't need Terraform — redeploy a
previously built image tag.

The deployed URL is printed by the verify job and visible in Google Cloud Console
under Cloud Run.

## Testing

```bash
uv run pytest               # Full suite (405 tests)
uv run pytest tests/test_auth.py -xvs  # Auth tests with verbose output
uv run pytest --cov         # Coverage report (96% target)
```

Tests use isolated in-memory SQLite. No external dependencies. See [CLAUDE.md](CLAUDE.md#testing) for auth fixture details.

## Stack

- **Backend:** FastAPI, FastMCP v3, SQLAlchemy (aiosqlite), WeasyPrint, Jinja2
- **Frontend:** React 19, TypeScript, Vite, TanStack Query (React Query), Tailwind CSS
- **Deployment:** Cloud Run, Terraform, GitHub Actions CI/CD
- **Design:** Stateless, $PORT-aware, 12-factor config (env vars)

## Project Status

**Phase 1d:** Operator SPA + JWT auth complete. 405 tests passing. See [CLAUDE.md](CLAUDE.md#project-state) for key files and non-obvious patterns.

**Phase 2 (planned):** Async Postgres, mutations (edit CV), operator integrations.

---

For questions or contributions, see [AGENTS.md](AGENTS.md) (detailed setup and troubleshooting) or [CLAUDE.md](CLAUDE.md) (internal patterns and commands).
