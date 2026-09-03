# AGENTS.md

## Python Environment

Targets Python 3.14 — do not use syntax newer than 3.14.

All dependencies are project-specific and managed by `uv` via `pyproject.toml`.
Never use `pip` or a `requirements.txt`. Install with:

```bash
uv sync --group dev
```

Add a dependency with `uv add <package>` (`uv add --group dev <package>` for dev-only).
Never use `uv pip` to manage dependencies — it bypasses `pyproject.toml` and the lockfile.

When running Python commands, use `uv run` to execute within the project virtual environment.

```bash
uv run <command>
```

## Git Workflow

- Branch from `main` as `feature/<name>`. Never commit directly to `main`.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`).
- Stage changes for review. Do not commit or push unless asked.
- No `Co-Authored-By:` trailers or tool-attribution lines in commits or PR bodies.

## Code Style

- Follow existing FastAPI + FastMCP patterns in `services/portfolio/main.py`
- Use `ruff` for linting and formatting
- Use `ty` for type checking
- Type-hint every public function and method, including return types
- Write Google-style docstrings for every public function and method
- Use `pathlib` for filesystem paths — never `os.path`
- Prefer f-strings over `str.format()` or `%` formatting
- Follow EAFP: handle the exception rather than pre-checking the condition
- Validate request bodies with Pydantic models
- Prefer idiomatic Python: comprehensions, generators, decorators, context managers, memory efficient data structures.
- **Avoid hardcoding file paths or line numbers in comments/docstrings.** A
  path or line reference goes stale the moment the referenced code moves —
  this repo has already had a rename (`app/` → `services/portfolio/`) break
  several such references across docs and docstrings. Prefer naming the
  function/class/fixture instead (e.g. "see the `auth_settings` fixture" or
  "see the `app.add_middleware(...)` block", not "see conftest.py:240" or
  "main.py:166-188"). If a path must be named, don't pin a line range.

## Commands

```bash
just dev-local            # run dev server with hot reload
just dev-spa              # run the operator SPA dev server
just code-quality         # ruff check + ruff format + ty type check
just test                 # run test suite with coverage (extra args pass through)
```

Note: `set dotenv-load` injects `.env` into every just recipe (dev server gets CONTACT_NAME/CONTACT_EMAIL etc.). A manually started uvicorn does NOT read `.env` — source it (`set -a; source .env; set +a`) or Swagger metadata stays empty.

## CSS Build Sync

`static/css/site.css` is a committed build artifact (Tailwind CSS output). It must be
rebuilt and committed whenever:

- Template classes change (e.g. adding Tailwind utilities to a new template)
- `tailwind.config.js` content paths change
- `node_modules` is recreated (CI does fresh install)

**Local rebuild:**

```bash
npm install          # install Tailwind + browserslist (first time only)
npm run css          # rebuild site.css from input.css + Tailwind config
```

**Pre-commit hooks** do NOT run `npm run css` — you must rebuild manually before
committing template class changes. If CI fails with a CSS diff, rebuild and commit
the updated `site.css`.

**CI/CD** runs `npm run css` as part of the build. A stale `site.css` causes a diff
check failure — the fix is always the same: rebuild locally and commit.

## Project

FastAPI + FastMCP CV rendering service. PDFs via WeasyPrint. Templates in `templates/`, themes in `services/portfolio/themes/`.

Deployed to **GCP Cloud Run** (internet-facing). CV data comes from GCS via `CV_DATA_GCS_URI`. The operator is the sole content author — there is no untrusted user input path.

## Codebase Map

```text
services/portfolio/
├── main.py              # FastAPI app assembly, MCP tools, lifespan, /mcp mount
├── constants.py         # Project paths (TEMPLATE_DIR, THEMES_DIR), cache/worker limits
├── routes.py            # REST endpoints: /, /health, /cv, /cv/html, /cv/preview, /cv/pdf, /api/v1/cv/tailor
├── cv_data.py           # Pydantic models + validate_cv_payload/load_cv_data
├── cv_source.py         # CvSource: local file or GCS object (generation-checked hot reload, example-file placeholder fallback)
├── pdf_generator.py     # PdfService class: cache, executor, sync/async PDF generation
├── rate_limiter.py      # slowapi Limiter, get_client_ip strategy, @limits stacked decorator
├── mcp_limits.py        # MCP tool rate limits (slowapi stubs + fastmcp request context)
├── guard_middleware.py  # Outermost access gate: allowlist/blocklist/bans/hours
├── ip_lists.py          # IP/CIDR parsing + membership checks
├── service_hours.py     # Scheduled availability window evaluation
├── failban.py           # Dynamic ban tracker fed by rate-limit violations
├── renderer.py          # Jinja2 rendering: render_html (CV) + render_template (pages)
├── dependencies.py      # get_pdf_service(request) dependency
├── settings.py          # Pydantic Settings — all runtime knobs, see .env.example
├── jd_input.py          # JD format normalization for /api/v1/cv/tailor: JSON/PDF/DOCX/txt/Markdown
├── schemas/
│   └── tailor.py        # TailorRequest (Pydantic body schema for the JSON JD format)
├── matching/
│   ├── __init__.py
│   ├── taxonomy.py      # Alias map, normalize_skill (UK→US word-level canonicalization), build_skill_index
│   ├── baseline.py      # Skill bank loader: validation, build_atom_index (canonical-first), get_baseline (mtime/size cache)
│   ├── parser.py        # extract_skills_from_jd (phrase/comma/token 3-phase) + extract_mentions (qualifier→expert/middle/basic, years-based)
│   ├── matcher.py       # match_skills (exact→substring→fuzzy, threshold≥0.8) + filter_atoms_by_level + sort_atoms_by_priority (bank helpers)
│   ├── selector.py      # reorder_skill_categories (F-shaped: matched first)
│   └── tailor.py        # tailor_cv(jd_text, baseline_atoms, live_cv) — bank-driven rebuild: mentions→level→trust→group; company_slug/extract_company
└── themes/
    ├── __init__.py      # Theme Protocol definition
    ├── classic.py       # CSS string
    ├── minimal.py       # CSS string
    ├── modern.py        # CSS string
    └── original.py      # CSS string — paper-CV look (Montserrat, centered header, pipes)

templates/
├── cv_base.html         # Base Jinja2 template
├── landing.html         # Root page: MCP config, API table, theme pick + Preview/PDF buttons
├── preview.html         # /cv/preview toolbar page embedding /cv/html in an iframe
├── _theme_head.html     # Shared partial: favicon link, Tailwind CDN + darkMode config + pre-paint bootstrap
└── _theme_toggle.html   # Shared partial: fixed light/dark toggle button (localStorage)

static/
└── favicon.svg          # Favicon served at /static/favicon.svg — swap this file to rebrand

data/
├── cv.json              # CV content (validated against CVData model)
├── cv_baseline.json     # Skill bank: atoms with level/priority/category_hint; SEARCH VOCAB FOR /api/v1/cv/tailor + MCP match_jd
└── cv_tailored-*.json  # File-fallback revisions ONLY (Postgres is primary storage, ADR-023 PR4) — written into data/tailored/ (settings.cv_tailored_dir) when /api/v1/cv/tailor can't reach the DB

config/
├── blocked_geo.txt      # GENERATED geo blocklist (ipdeny RU IR KP BY CU SY VE MM) — refresh: just update-geo-blocklist
└── mcp_clients.json     # MCP tab definitions (snippets, docs links, check markers, verified stamps) — shared with CI drift-check

.github/workflows/
├── ci-cd.yml            # INFRA only (paths: terraform/**): tflint+checkov → Infracost → plan → gated apply
├── deploy-app.yml       # APP only (paths: services/portfolio/, frontend/, services/, Dockerfiles): test → build → gcloud run deploy
└── mcp-docs-drift.yml   # monthly vendor-docs marker check (see ADR-014)

scripts/
├── check_mcp_docs.py    # marker check + verified-stamp bump for config/mcp_clients.json
└── deploy-cloud-run.sh  # idempotent bootstrap stages ONLY (never creates the GCP project); SAs/APIs/registry are Terraform's

terraform/              # Phase 1a edge IaC (single managed env, no per-env split)
├── main.tf             # composes run + edge_lb + dns modules; separates workloads from host_routing
├── versions.tf         # google provider pin + commented GCS remote-state backend (bootstrap via `just deploy bootstrap-state`)
├── variables.tf        # project/region/apex_domain, services (Cloud Run), host_routing, static_assets (uploads now commented out)
├── outputs.tf          # LB IP, service/neg names, DNS nameservers, static/uploads bucket names
├── .tflint.hcl         # tflint config (built-in ruleset only; no init/network needed)
├── terraform.tfvars.example  # shape reference; real terraform.tfvars is gitignored
├── backend.tfbackend.example # GCS backend config (bucket/prefix); real .tfbackend gitignored
├── .terraform.lock.hcl # committed provider lock
└── modules/
    ├── cloud_run_service/  # reusable Cloud Run service + serverless NEG (api-core/api-games/spa-origin/workers)
    ├── edge_lb/            # global IP, managed certs, NEG backend services, URL map + CDN path_routes (assets prefix)
    ├── static_bucket/      # public-read GCS origin for Cloud CDN (the ONE allowlisted exception)
    ├── uploads/            # PRIVATE user-content bucket (deny-public, enforced) — signed-URL only; commented out in root
    └── dns/                # Cloud DNS zone (DNSSEC on) + A records for apex + www/api/app/games -> LB IP

tests/
├── conftest.py          # AsyncClient fixture via ASGITransport
├── test_api.py          # REST endpoint tests
├── test_cv_data.py      # Data validation tests
├── test_cv_source.py    # CvSource file/GCS modes, hot reload, placeholder fallback
├── test_guards.py       # ip_lists, service_hours, failban, GuardMiddleware tests
├── test_mcp.py          # MCP tool tests
├── test_mcp_limits.py   # MCP tool rate-limit tests
├── test_pdf_generator.py # PDF generation tests
├── test_rate_limiter.py # Rate limiter / client-IP strategy tests
├── test_consent.py      # GDPR/RODO recruiter-clause tests (HTML/preview/PDF cache)
├── test_tailor_auth.py  # TailorAuthMiddleware tests: 401/503 paths, scope, constant-time compare
├── test_jd_input.py     # JD format dispatch tests (JSON/PDF/DOCX/txt/Markdown) for /api/v1/cv/tailor
├── test_deny_public.py  # ensure_deny_public guard: enforce/deny-public + CDN-origin exception
├── test_matching/       # Skill matching pipeline: taxonomy, parser, matcher, selector, tailor
│   ├── test_taxonomy.py # Alias map + normalize_skill + build_skill_index
│   ├── test_parser.py   # extract_skills_from_jd (phrase/comma/token)
│   ├── test_qualifier.py # extract_mentions — qualifier→level, years-based, dedup, backward-compat
│   ├── test_properties.py # Hypothesis properties: normalize fixpoint, UK/US canonicalization, mention/match invariants
│   ├── test_baseline.py # Bank loader validation, atom index (canonical-first), mtime cache, structural real-bank checks
│   ├── test_matcher.py  # match_skills — exact→substring (fuzz.partial_ratio)→fuzzy + filter_atoms_by_level + sort_atoms_by_priority
│   ├── test_selector.py # reorder_skill_categories (F-shaped ordering)
│   └── test_tailor.py   # tailor_cv() bank-driven rebuild: level filter, trust policy, grouping, pass-through
└── test_e2e.py          # Playwright browser flows (copy, dark mode, consent click-through); run: just test-ui

docs/
├── architecture.md      # System components, data flow, endpoints
├── api.md               # Explicit REST contract: paths, params, bodies, status codes
├── design.md            # Design principles, patterns, constraints
├── decisions.md         # ADR-style decision log
└── refresh-token-families.md  # Refresh rotation, reuse detection, what revocation kills

Dockerfile              # Production container image
.editorconfig           # Editor defaults: Ruff mirror for Python, web-standard indents
justfile                # Recipes: setup, dev, code-quality, test, test-pdf, build, run, deploy, mcp-* — operator GCP ops use `just deploy <stage>` (scripts/deploy-cloud-run.sh), no direct gcloud recipes
pyproject.toml          # Python 3.14+, deps, ruff/ty config, pytest asyncio_mode=auto
```

### Key Patterns

- **Theme contract**: `services/portfolio/themes/__init__.py` defines `Theme` Protocol requiring `CSS: str`. Theme modules validated at import time via `isinstance(module, Theme)`.
- **Theme styling scope**: themes set ONLY fonts/sizes/colors; structure (list markup, list-style, geometry, fallbacks) lives in `cv_base.html` as zero-specificity `:where()` defaults so theme overrides win regardless of stylesheet order (`{{css}}` is injected BEFORE the base block).
- **Semantic markup + running-element gotcha**: cv_base.html uses HTML5 semantics (`main`/`header`/`address`/`article`/`h3`/`time`/`footer`) with classes as styling hooks; UA defaults are neutralized via `:where(address)/:where(h3)` resets. The `.cv-footer` running element MUST stay first in `<body>`: CSS GCPM makes a running element available to margin boxes only from its document page onward, so moving it to the end silently drops footers from all but the last page.
- **PDF visual verification**: when measuring generated PDFs with pdfplumber, check EVERY page and EVERY glyph variant — WeasyPrint's UA stylesheet adds native list markers (duplicate small bullets) unless `list-style: none`, and abs-pos offsets anchor to the padding box. Page-1-only checks have shipped real bugs (overlapped/duplicated bullets in the original theme).
- **PDF cache**: LRU-bounded (50 entries) `OrderedDict` keyed by `(theme, sha256(cv_json + consent-tag))` — the recruiter GDPR/RODO clause (`consent`/`company` query params) is part of the key, so different companies never share cached PDFs. Shared `_get_or_render_pdf()` helper for sync/async paths.
- **PDF functions**: `generate_cv_pdf(theme, cv_json)` and `generate_cv_pdf_async(theme, cv_json)` both require explicit `cv_json` dict — no module-level state.
- **Renderer context boundary**: `_build_render_context` in `services/portfolio/renderer.py` strips only the renderer-owned keys (`css`, `consent_enabled`, `consent_company`) from incoming CV data and applies its own values last — never splat raw CV dicts into `template.render`. Harmless extra metadata passes through (`CVData` stays `extra="allow"`).
- **PDF URL fetch policy**: all WeasyPrint construction goes through `_generate_pdf_sync` with a deny-all `url_fetcher` (`_URLFetchDeniedError` for every scheme). Never construct `HTML(...)` without it; browser static assets are unaffected by this boundary.
- **Rate limiting**: slowapi `Limiter` keyed by `get_client_ip` (XFF-entry / header / socket-peer strategies). REST uses the `@limits(...)` stacked decorator (burst + sustained, loopback-socket-peer exempt); MCP tools enforce via `services/portfolio/mcp_limits.py` stubs + `get_http_request()`. `GuardMiddleware` (added last = runs first) handles allowlist/blocklist/dynamic bans/service hours; `/health` always passes. Loopback exemptions (limits, failban) are gated by `TRUST_PROXY`: proxied platforms (Cloud Run peer = 127.0.0.1 for everyone) MUST set `TRUST_PROXY=true` + `CLIENT_IP_XFF_ENTRY=2` or limits silently stop applying.
- **IP access lists**: `parse_ip_list` accepts commas, whitespace, and newlines; `#` comments run to end of line (stripped BEFORE comma splitting — a comma inside a comment must not split tokens). Inline env values merge with `*_FILE` files; missing configured file = startup failure. Large geo lists MUST use the file form (execve caps env args at ~128KB); regenerate via `just update-geo-blocklist`.
- **Image packaging**: the image ships `data/cv.example.json` ONLY (never real cv.json — CV content comes from GCS via `CV_DATA_GCS_URI`) plus `config/` (geo blocklist, MCP tab definitions). `.dockerignore` and `.gcloudignore` both use `data/*` + `!data/cv.example.json`; gcloud builds submit applies `.gcloudignore` verbatim when present, otherwise it derives one from `.gitignore`, which excludes personal data.
- **Operator edits `data/cv.json` by hand — unannounced**: the operator maintains the live CV directly and does NOT notify sessions of every edit. Always re-read `data/cv.json` (and `data/cv_baseline.json`) freshly at task start; never assume content seen earlier is still current. Re-validate with `validate_cv_payload` before relying on it. Where granularity matters (trust passes only for keyword-only, bank-aligned items), the operator keeps that contract when hand-editing — a task that runs into a dropped atom should check the CURRENT file, not blame stale structure.
- **Builder image pin**: the Dockerfile builder stage is digest-pinned (`ghcr.io/astral-sh/uv:0.12.5@sha256:...`); bump deliberately via `docker buildx imagetools inspect ghcr.io/astral-sh/uv:<tag>` and update both Dockerfile and docs together. `python:3.14-slim` stays tag-based by scope decision.
- **Terraform IaC (Phase 1a edge + 1b CDN/uploads)**: single managed env, flat `terraform/` (no per-env split). Workloads (distinct Cloud Run services) are separate from `host_routing` (hostname → workload) because `www.` and `api.` both route to `api-core`. Pre-commit enforces `terraform fmt` (format), `tflint` (logic, built-in ruleset only — no `--init`), `checkov` (security, isolated via `uvx --from 'checkov'` — NOT a dev-dep because checkov pins `packaging<24.0` vs `fastmcp` `>=24.0`), and the `terraform-deny-public` guard. checkov's `--skip-check` list (see `.pre-commit-config.yaml` for the current set and a one-line justification per check) covers the ONE public-read Cloud CDN origin bucket (`modules/static_bucket`, `allUsers` objectViewer), CI/CD-required deployer IAM, the disabled Cloud Armor module, and CSEK on the Artifact Registry repo (Google-managed encryption is sufficient for this single dev env). `tflint` and `checkov` also run in CI (`ci-cd.yml`'s `terraform-quality` job); `terraform-deny-public` stays pre-commit-only. The path-scoped guarantee that every OTHER bucket has `public_access_prevention="enforced"` + uniform access and no anonymous write is enforced by `scripts/ensure_deny_public.py` (see `tests/test_deny_public.py`) — inline `#checkov:skip` is unreliable in the pinned checkov (measured "Skipped: 0"), and checkov `skip-check` can't be path-scoped, hence the custom guard. `modules/uploads` is a PRIVATE deny-public bucket for user avatars/photos, signed-V4-URL-only (writes/reads via server-minted short-TTL object-scoped URLs; `user_id`-scoped keys) — currently **commented out** in root `main.tf`+`variables.tf`+`outputs.tf` so the operator can practice `tf plan`/`apply` on the CDN piece first; uncomment all three together. Remote state + locking: `just deploy bootstrap-state` creates the versioned GCS bucket (`<project>-<GCP_ENV>-tfstate`, `GCP_ENV` defaulting to `production`; `versions.tf` pins the backend to it) — the GCS backend locks via an object write-hold in that SAME bucket, so there is **no separate lock bucket**; never disable versioning on it. Infra deep-dive + signed-URL recipes: `docs/cloud-cdn.md`. Any infra file that fails `terraform validate` or the pre-commit gates must be fixed before landing.
- **CSP hash lifecycle**: `SecurityHeadersMiddleware` computes SHA-256 hashes of all inline `<script>` blocks in `templates/**/*.html` at **import time** and bakes them into `_CSP_DIRECTIVE` (a module-level constant). Changing a template script requires a server restart — the browser blocks scripts whose hash doesn't match the CSP (fail-safe). Dev with uvicorn `--reload` handles this automatically; production (Cloud Run) needs a new revision. `test_csp_script_hashes_match_templates` independently recomputes hashes from templates to catch stale values.
- **MCP client tabs**: snippets live in `config/mcp_clients.json` (single source of truth with `scripts/check_mcp_docs.py`); `routes.load_mcp_clients()` validates at import and aborts startup on a broken file. The monthly `mcp-docs-drift` workflow re-checks each vendor's docs for the expected markers — drift opens an issue, a clean run auto-commits refreshed `verified` stamps. Never add a second copy of the snippet data in code. Keep the JSON byte-identical to `json.dumps(..., indent=2)` output so stamp bumps produce stamp-only diffs; the file is read once at import, so dev-server reload needs `touch app/routes.py` after editing it.
- **MCP tools**: Return base64 string for `generate_cv_pdf_tool` (MCP is JSON-only). Re-raises `ToolError` without wrapping.
- **JD input formats** (`services/portfolio/jd_input.py`): `/api/v1/cv/tailor` accepts JSON, PDF (`pypdf`), DOCX (`python-docx`), txt, and Markdown via a `_PARSERS` media-type registry. Generic/unknown content types get magic-byte sniffing (`%PDF`, `PK\x03\x04`); everything else falls back to raw text so pasting a JD just works. 10 MB body cap is enforced once at `parse_jd_input` entry (all branches). Corrupt/undecodable files raise `ValueError` → the route maps it to 422. `.doc` (legacy binary) is intentionally NOT supported — too old/edge-case.
- **Tailor auth surface** (`services/portfolio/auth/middleware.py::JWTAuthMiddleware`): `POST /api/v1/cv/tailor` is gated on a JWT access token whose `role` claim is `admin`. The `?tailored=` revision read on `/cv/html`, and the always-protected `GET /api/v1/cv` / `GET /api/v1/cv/pdf` (operator-only equivalents of the public `/cv` / `/cv/pdf`), require a JWT with the `cv:read` scope — header-only, no `?token=` fallback (tailored previews/PDFs are operator-SPA-only). The public `/cv`, `/cv/preview`, and `/cv/pdf` never accept `tailored`. The tailoring surface migrated off the prior static-bearer-token design (see ADR-018 marked superseded, ADR-022). Tokens are HS256 (Phase 1c simplification over the ES256 plan; ES256 swap is local to `services/portfolio/auth/crypto.py::_REQUIRED_SCHEME` when a second service verifies, ADR-022). **Fail-closed**: with no signing key, both routes return `503`; missing/invalid token → `401`; wrong role/scope → `403`. The middleware is mounted in `services/portfolio/main.py` between `GuardMiddleware` and `SecurityHeadersMiddleware` so global geo/failban/service-hours still applies, and 401/403/503 responses still carry CSP/etc. headers.
- **Bank-driven tailoring** (`services/portfolio/matching/`): `/api/v1/cv/tailor` + MCP `match_jd` rebuild the CV's skills from `data/cv_baseline.json` bank atoms — NOT the live CV. Pipeline: `extract_mentions` (qualifier→level) sets a required level per canonical (strongest wins) → `filter_atoms_by_level` drops atoms below it (expert 3 > middle 2 > basic 1; a bare mention = no constraint) → bounded fuzzy fallback (300 tokens, `fuzz.partial_ratio`/`fuzz.ratio` ≥ 0.8) catches typos WITHOUT re-matching any word that is already a known index key (else a level-filtered atom gets smuggled back in — regression-tested) → trust policy drops atoms not vouched for on the live CV → survivors group by `category_hint` ("Additional skills > …" → `additional_skills`) ordered by the **live CV's canonical structure** — group → sub_category → item positions from `_canonical_skill_order(live_cv)` in `services/portfolio/matching/tailor.py` — so "Python" (languages) always heads "Backend development" and top-level groups follow the public CV regardless of JD mention order; unmatched slots keep bank `priority` (high→low), stable. `get_baseline()` (services/portfolio/matching/baseline.py) validates loudly (`BaselineError`), caches by (path, size, mtime) for hot reload, ignores `deferred`, and inserts canonical names BEFORE aliases so an alias can never shadow a real atom. `/api/v1/cv/tailor` persists the revision to Postgres and returns its `id` as `saved_to` (falls back to a `cv_tailored-<UTC-ts>.json` file in `settings.cv_tailored_dir` on any DB error, ADR-023 PR4); a no-match JD yields EMPTY skill sections (deliberate verdict). Tests must point `settings.cv_baseline_path`/`cv_tailored_dir` at test-owned paths — the autouse `tailor_settings` fixture in `tests/conftest.py` does this for every test. **Trust index wants granular items**: the live-CV skill index keys are raw/tokenized item strings, so a bank atom passes trust only when its canonical name appears as its own item — compound comma-joined items (e.g. `"Docker (multi-stage …), Docker Compose"`) fragment into keys like `"docker (multi-stage"` and get dropped. Keep skill items keyword-only, one bank-aligned name each; `normalize_skill` strips trailing `()` and keeps digits for tool names (D2/S3).
- **Tests**: Use `httpx.AsyncClient` + `ASGITransport` with `asyncio_mode = "auto"` — async tests need no `@pytest.mark.asyncio` marker.
- **No adversarial self-tests**: the operator is the only content author. Tests must not protect against scenarios where the attacker and defender are the same person (e.g. injecting `"css":"evil"` into your own CV JSON). Security-adjacent code (URL fetcher denial, error sanitization) is justified by the public Cloud Run surface; pure self-inflicted edge cases are not.
- **Tests are CV-data-independent**: tests must NOT assert on `data/cv.json` wording, names, or counts (the file is user content that changes often). Use the `SYNTHETIC_CV` fixtures from `tests/conftest.py` (`synthetic_cv`, `synthetic_cv_path`, `pdf_service`, `override_pdf_service`). Only structural smoke checks (e.g., "experience is a list") are allowed against the real file.
- **Chrome DevTools MCP privacy**: NEVER attach to or enumerate the user's real browser window/tabs. Always open test pages with `isolatedContext` set (incognito-equivalent) and close them when done.

## Markdown Style

- **Always tag fenced code blocks with a language.** Never a bare ` ``` `.
  Drives syntax highlighting and satisfies markdownlint MD040.
- Use `text` for plain output, ASCII diagrams, and command output;
  `bash`, `python`, `hcl`, `yaml`, `json`, `sql`, `mermaid` where they apply.
- Surround lists and fenced blocks with blank lines (MD032, MD031).

```bash
uv run pytest
```

```text
Plan: 3 to add, 0 to change, 0 to destroy.
```

## Paired documentation

Two infra docs exist in **two versions**: a gitignored operator copy holding
real values, and a sanitised copy committed to the public repo.

| Local (gitignored, real values) | Committed (sanitised) |
| --- | --- |
| `.agent/infrastructure_local.md` | `docs/infrastructure.md` |
| `.agent/architecture-diagrams_local.md` | `docs/architecture-diagrams.md` |

**Rule: never update one without the other.** Whenever a change introduces or
alters a concrete infrastructure value — project id or number, IP address,
domain or hostname, DNS zone, bucket, service-account email, WIF provider path,
Artifact Registry path, port, image tag scheme — update the local copy with the
real value **and** the committed copy with a placeholder, in the same change.

This applies to edits made directly to these files and to changes that *produce*
new values: `terraform apply`, `gcloud` commands that create or rename
resources, new Terraform modules or outputs, DNS/registrar changes, and new
GitHub secrets or variables.

Placeholders in the committed copies use angle brackets: `<PROJECT_ID>`,
`<PROJECT_NUMBER>`, `<APEX_DOMAIN>`, `<DNS_ZONE>`, `<LB_IPV4>`,
`<GITHUB_OWNER>/<REPO>`, `<registrar>`. Keep a `verify` command beside each
value so a reader can obtain the real one themselves.

The repository is **public** — never commit a real project number, service
account email, state bucket name, or WIF provider path.

## Self-Correction Protocol

> This section defines how this file stays alive and accurate.

1. **Stale map?** If you discover that the Codebase Map above doesn't match reality, **update it now** before continuing your task. Don't leave it for later.

2. **User correction?** If a human corrects your behavior (e.g., "don't use that API", "run tests this way"), add the correction to the appropriate section of this file (Local Norms, Guardrails, or Patterns & Gotchas) **before continuing any other work**. Do not defer this to the end of the task. Future sessions depend on it.

3. **Repeated friction?** If you notice yourself doing the same multi-step workflow more than once, consider creating a new skill in `skills/`. See `instructions/self-improving-agent.instructions.md` for the procedure.

4. **Post-task reflection.** After completing a significant task, briefly review:
   - Did anything surprise you?
   - Did you take a path that could be shortcutted next time?
   - If yes, record the insight in this file or as a new skill.

5. **Promotion rule.** Before promoting a learning to this file, check `.learnings/LEARNINGS.md` for related entries. If a pattern has `Recurrence-Count >= 3`, has been seen across at least 2 distinct tasks, and occurred within a 30-day window, it qualifies for promotion. Write the promoted rule as a short prevention rule, not a long incident write-up.

6. **Docs sync.** When architecture, design, or ADRs change, update `docs/architecture.md`, `docs/design.md`, or `docs/decisions.md` respectively. Do not leave implementation drift between code and docs. Paired infra docs have an extra rule — see [Paired documentation](#paired-documentation).
