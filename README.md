# CV REST/MCP Server

FastAPI + FastMCP service rendering a CV as JSON, HTML, themed PDFs, and MCP tools. Operator login guards mutating/authed endpoints; the same JD you're applying to can be tailored against your skill bank and checked for gaps. See [docs/using-gap-analysis.md](docs/using-gap-analysis.md) for the "what should I learn next?" workflow.

## Architecture

Two services, one codebase:

| Service | Role                                               | Deployed as        |
| ------- | -------------------------------------------------- | ------------------ |
| **API** | FastAPI + FastMCP; renders CV; validates operators | `api-core` image   |
| **SPA** | React 19 + Vite; operator login & dashboard        | `spa-origin` image |

**Locally:** Both run in dev mode (API on 8080, SPA on 5173). `just dev-local` starts the API with hot reload; `just dev-spa` starts the SPA (separate terminal).

**Cloud Run:** Separate services. SPA nginx serves static assets (Vite-hashed); API is JSON-only. A reverse proxy (or CDN) routes `/app.domain` → SPA and `/api.domain` → API.

## Authentication

Operators sign in at `/login` (served by the SPA) with username/password. API issues an HS256 JWT access token plus a refresh token; both are Postgres-backed (`DATABASE_URL`, required, no default — see [CLAUDE.md](CLAUDE.md#project-state)).

**Unauthenticated requests:**

- `GET /`, `GET /health` — allowed
- `GET /cv`, `/cv/html`, `/cv/preview`, `/cv/pdf` (live CV, no `tailored` selector) — allowed
- Everything under `/api/v1/*`, plus a `?tailored=` selector on the public CV routes — JWT required

See [CLAUDE.md](CLAUDE.md#authentication) for env vars (`JWT_SIGNING_KEY`, `FIRST_ADMIN_USERNAME`, etc.).

## Getting Started

**Just want to see the CV locally?**

```bash
just setup && just dev-local
```

Open <http://localhost:8080>. `just dev-spa` (separate terminal) starts the operator SPA on 5173 for login and the tailoring/gap-analysis UI.

**Want to modify the CV data?**

Edit `data/cv.json` (validated against `CVData` in `services/portfolio/cv_data.py`). Restart the API server.

Set `CV_DATA_PATH` env var to point to a different JSON file. See `data/cv.example.json` for the full schema.

**Want to try job-description gap analysis?**

See [docs/using-gap-analysis.md](docs/using-gap-analysis.md).

**Ready to deploy to GCP?**

See [Deployment](#deployment) below.

## API

### REST Endpoints

Public (no auth):

| Method | Path                        | Description                |
| ------ | --------------------------- | --------------------------- |
| GET    | `/`                         | Landing page                |
| GET    | `/health`                   | Health check                |
| GET    | `/cv`                       | Live CV as JSON             |
| GET    | `/cv/html?theme=<name>`     | Live CV rendered as HTML    |
| GET    | `/cv/preview?theme=<name>`  | Preview page with toolbar   |
| GET    | `/cv/pdf?theme=<name>`      | Live CV as PDF (attachment) |

Operator-only (JWT required — `cv:read` / `cv:manage` scopes, see [AGENTS.md](AGENTS.md)):

| Method | Path                                  | Description                                     |
| ------ | -------------------------------------- | ------------------------------------------------ |
| GET    | `/api/v1/cv`                           | Operator CV as JSON (supports tailored revisions) |
| GET    | `/api/v1/cv/pdf`                       | Operator CV as PDF                              |
| POST   | `/api/v1/cv/tailor`                    | Tailor the CV against a job description         |
| GET    | `/api/v1/revisions`                    | List saved tailored revisions                   |
| POST   | `/api/v1/postings`                     | Store a job posting                             |
| GET    | `/api/v1/postings`                     | List stored postings                            |
| POST   | `/api/v1/postings/{id}/analyze`        | Run gap analysis on a posting                   |
| GET    | `/api/v1/postings/{id}`                | Read a stored gap report                        |
| GET    | `/api/v1/gaps/roadmap`                 | Ranked "what to learn next" roadmap             |
| \*     | `/api/v1/tracked-boards*`              | CRUD for ATS boards under continuous monitoring |
| \*     | `/api/v1/documents/{kind}`             | CRUD for operator documents (CV / skill bank / JD vocabulary) |

See [docs/using-gap-analysis.md](docs/using-gap-analysis.md) for how the gap-analysis endpoints fit together, and [docs/api.md](docs/api.md) for the full contract.

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

| Tool                   | Parameters                     | Returns                                |
| ---------------------- | ------------------------------- | --------------------------------------- |
| `get_cv`               | —                                | JSON object with full CV data           |
| `get_available_themes` | —                                | `list[str]` of theme names              |
| `generate_cv_pdf_tool` | `theme: str`                     | Base64-encoded PDF bytes                |
| `match_job_posting`    | `posting_text: str`, `title: str = ""` | Tailored CV JSON matched against a posting |

## Themes

Four built-in themes: `classic`, `minimal`, `modern`, `original`. Defined in `services/portfolio/themes/<name>.py` as CSS strings.

Add a new theme: create `services/portfolio/themes/yourname.py` with a `CSS` constant.

## Rate Limiting

Per-IP (`X-Forwarded-For`-aware behind a trusted proxy), in-memory. Loopback peers exempt in local dev. Every limited endpoint stacks a per-minute burst cap with a per-hour sustained cap; a sample:

| Endpoint                  | Limit                    |
| -------------------------- | ------------------------- |
| `/`                         | 30/min, 120/hour          |
| `/health`                   | 60/min                    |
| `/cv`, `/api/v1/cv`         | 30/min, 600/hour          |
| `/cv/html`, `/cv/preview`   | 30/min, 300/hour          |
| `/cv/pdf`, `/api/v1/cv/pdf` | 5/15min, 15/hour          |
| `/api/v1/cv/tailor`         | 10/min, 60/hour           |

## Development

All commands use `uv` for dependency management:

```bash
uv sync --group dev     # Install dependencies (first time)
uv run pytest           # Run tests (522 total)
uv run pytest -x        # Stop on first failure
just code-quality       # Ruff + type check
just dev-local          # Start the API with hot reload
just dev-spa            # Start the SPA (separate terminal)
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
just dev-local   # API, port 8080
just dev-spa     # SPA, port 5173 (separate terminal)
```

Both start with hot reload. No setup required beyond `just setup`.

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
| `services/`, `frontend/`, Dockerfiles | `deploy-app.yml` | lint + tests → build images to Artifact Registry → `gcloud run deploy` → verify |
| `terraform/` | `ci-cd.yml` | tflint + checkov → Infracost → `terraform plan` → **approval gate** → `terraform apply` |

An app-only commit never runs Terraform, and an infra-only commit never rebuilds
images. Use `[skip deploy]` in a commit message to run checks without deploying.

Infra applies are gated on the `production` GitHub Environment: `terraform plan` posts its
output to the PR, and the apply job waits for a required reviewer before running
the exact reviewed plan. Application rollbacks don't need Terraform — redeploy a
previously built image tag.

The deployed URL is printed by the verify job and visible in Google Cloud Console
under Cloud Run.

## Testing

```bash
uv run pytest               # Full suite (522 tests)
uv run pytest services/portfolio/tests/test_auth.py -xvs  # Auth tests with verbose output
uv run pytest --cov         # Coverage report (96% target)
```

Tests run against a real, ephemeral Postgres via `testcontainers` (Docker required). See [CLAUDE.md](CLAUDE.md#testing) for auth fixture details.

## Stack

- **Backend:** FastAPI, FastMCP v3, SQLAlchemy (asyncpg/psycopg), Alembic, WeasyPrint, Jinja2
- **Frontend:** React 19, TypeScript, Vite, TanStack Query (React Query), Tailwind CSS
- **Database:** Cloud SQL Postgres (Auth Proxy), Alembic-migrated
- **Deployment:** Cloud Run, Terraform, GitHub Actions CI/CD
- **Design:** Stateless, $PORT-aware, 12-factor config (env vars)

## Project Status

**Phase 2:** Postgres-backed users, revisions, and gap analysis; JD tailoring against a skill bank; continuous ATS-board monitoring feeding a ranked learning roadmap. 522 tests passing. See [CLAUDE.md](CLAUDE.md#project-state) for key files and non-obvious patterns.

---

For questions or contributions, see [AGENTS.md](AGENTS.md) (detailed setup and troubleshooting) or [CLAUDE.md](CLAUDE.md) (internal patterns and commands).
