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
`just deploy upload-cv`, no redeploy. If the object is absent or invalid at boot,
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

## ADR-015: Unified CI/CD workflow with automatic main deployment

**Context.** Deploys were copy-paste gcloud blocks in a checklist. The team
wanted PR/main CI (lint, types, tests) and a path from manual deploys to
continuous deployment without long-lived cloud credentials in GitHub.

**Decision.** `.github/workflows/cd.yaml` runs ruff check/format-check, ty,
and pytest on pull requests targeting main and pushes to main. A successful
push to main then authenticates via Workload Identity Federation (`id-token:
write` only on the deploy job; no key material) and executes
`scripts/deploy-cloud-run.sh build`, then `deploy`, then `verify` as separate
commands. The deploy job is serialized and `[skip deploy]` skips only that job.
GitHub-native CI skip tokens skip the entire workflow.

That script is
the single source of deploy truth — it mirrors the checklist stages
(bootstrap/upload-cv/build/deploy/verify) and is idempotent; the same file
serves local runs and CI so the two paths cannot drift. Project creation is
deliberately out of scope: `GCP_PROJECT` must reference an existing project,
validated at stage start. A one-time `wif` stage creates the identity pool,
provider, and least-privilege deployer SA (run.admin + cloudbuild builder +
browser for the script's project-access probe + serviceAccountUser scoped to
the Cloud Build and runtime service accounts only) and prints the exact
`gh secret set` commands.

**Repo wiring (one-time, per repo).** The workflow reads plain repo
*variables* for non-sensitive config and WIF identifiers as *secrets*. The
`wif` stage prints these with real values filled in:

```bash
gh variable set GCP_PROJECT --body "<project-id>" # required
gh variable set GCP_REGION  --body "europe-west1" # optional — script default when unset
gh variable set SVC_NAME    --body "<name>"       # optional — default = repo name
gh secret set GCP_WIF_PROVIDER --body "<pool-full-path>/providers/gh-actions"
gh secret set GCP_DEPLOY_SA    --body "<name>-deployer@<project>.iam.gserviceaccount.com"
```

`SVC_NAME` decouples the deployed identity from the repo name: it names the
Cloud Run service, the image tag, and both derived service accounts
(`${SVC_NAME}-runtime`, `${SVC_NAME}-deployer`). Locally it travels via
`.env`; in Actions via `vars.SVC_NAME`. Because the deployer SA name derives
from it, changing `SVC_NAME` means re-running `just deploy wif` locally and
updating `GCP_DEPLOY_SA` with the freshly printed value — the other three
wiring values are unaffected. A rename deploys *alongside* the old service;
delete the old one manually once the new URL is verified. The verify stage
prints the URL using `gcloud run services describe "$SVC_NAME" --region
"$GCP_REGION" --format='value(status.url)'`. The same URL is visible in
Google Cloud Console under Cloud Run, the service, then URL. Service-account
IDs do not form part of the URL.

**Consequences.** Zero secrets stored in GitHub beyond WIF identifiers;
deploy provenance is auditable via Actions history. Runtime least-privilege is unchanged: the deployer can
build images and push revisions but holds no data-plane access to the CV
bucket.

## ADR-016: Vendored Tailwind CSS as CSP prerequisite

**Context.** The landing/preview pages loaded Tailwind from a third-party CDN
via a `<script>` tag with no SRI or nonce — supply-chain risk and a blocker
for any strict `Content-Security-Policy` (F-09).

**Decision.** Tailwind is compiled at build time with the pinned CLI scanning
`templates/**/*.html`; the generated `static/css/site.css` is committed and
served by FastAPI. The runtime never loads Tailwind or executes a CSS
compiler. CI regenerates the stylesheet and fails on stale output.
Inline-script hashing/extraction (dropping `'unsafe-inline'`) remains the
next CSP step; the vendoring itself is complete.

**Consequences.** No third-party runtime dependency; deterministic styling;
one extra build step (`just css`) that CI keeps honest.

## ADR-017: Phase 5 defense-in-depth — renderer context, PDF fetch guard, uv pin

**Context.** Audit findings F-08/F-10/F-12: WeasyPrint's default URL fetcher
is latent SSRF/local-file-read; `extra="allow"` plus `**cv` splat let a stray
`"css"` key in cv.json 500 every render path; the builder image floated on
`uv:latest`.

**Decision.**

1. `render_html` builds its context through `_build_render_context`, which
   strips only the renderer-owned keys (`css`, `consent_enabled`,
   `consent_company`) and applies its own values last; all other extra CV
   metadata passes through untouched (`CVData` keeps `extra="allow"`).

2. All WeasyPrint construction goes through `_generate_pdf_sync`, which now
   passes a deny-all `url_fetcher` raising `_URLFetchDeniedError` for every
   URL scheme, including `file://`, HTTP(S), and `data:`. Browser-served
   static assets are unaffected — the boundary is PDF rendering only.

3. The Dockerfile pins the builder stage to
   `ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1`
   (multi-platform manifest digest). `python:3.14-slim` stays tag-based by
   explicit scope decision.

**Consequences.** Renderer controls cannot be shadowed by payload keys; PDF
templates are structurally unable to reach network or filesystem resources;
the builder binary is immutable per rebuild. Cost: two private helpers and a
digest that must be bumped deliberately when uv updates.

## ADR-018: Bearer-token auth for `POST /cv/tailor`

**Context.** The `/cv/tailor` endpoint exists to match a job description
against the skill bank. The endpoint is otherwise public, which is fine for
the existing scope (the live CV is the public surface; the tailor flow is
read-only against the live CV). However, the endpoint consumes a
`cv_baseline.json` skill bank and writes `cv_tailored-<ts>.json`
revisions — both of which raise the operator's risk profile: anyone on
the internet could trigger tailoring and write revision files, and the
baseline is a source of atoms that affect what recruiters see in tailored
outputs.

**Options considered.**

1. *IP allowlist via `TailorGuardMiddleware`* — mirrors the existing
   `GuardMiddleware` shape. Rejected: adds new CIDR parsing/inline+file
   plumbing, requires the operator to know their egress IP (which
   changes on Cloud Run), and creates a maintenance burden without
   buying meaningful security beyond what global `GuardMiddleware`
   already provides.
2. *OAuth / session auth* — proper identity. Rejected as overkill for a
   single-operator endpoint; deferred to a separate project.
3. *Bearer token via dedicated `TailorAuthMiddleware`* (chosen).
   Single static token, `Authorization: Bearer <token>`, constant-time
   compare via `secrets.compare_digest`, fail-closed on missing config.
   ~50 lines, no new dependencies, works from any IP.

**Decision.** `app/tailor_auth.py::TailorAuthMiddleware`. Path-scoped
to `POST /cv/tailor` only; mounted between `GuardMiddleware` and
`SecurityHeadersMiddleware` in `app/main.py` so the global guard still
applies (geo/failban/service-hours) and the 401/503 responses still
carry CSP/SAMEORIGIN headers. Token resolved at request time from
`settings.tailor_bearer_token` (inline) or
`settings.tailor_bearer_token_file` (file form, preferred for prod,
file wins on conflict). The presented token is never logged. The
middleware is a no-op on every other route — the scope test in
`tests/test_tailor_auth.py` is the regression guard for that.

**Consequences.** `/cv/tailor` is no longer callable anonymously; the
public surface (`/cv`, `/cv/html`, `/cv/pdf`, `/cv/preview`, `/health`,
MCP tools) is unchanged. Operationally: a misconfigured deploy returns
503 (fail-closed), not 401; the startup log line warns when the token
is unset. Rotation: restart the service with a new `TAILOR_BEARER_TOKEN`
value. For higher-security deployments, the deploy script can replace
the inline value with a Secret Manager reference via `--set-secrets`
without changing app code. Single static token, no replay protection,
no per-user audit — acceptable for single-operator, not for multi-user.

## ADR-019: Bank-driven tailoring — `/cv/tailor` converges on the skill bank

**Context.** The plan ("bank-driven tailor") calls for matching job
descriptions against `data/cv_baseline.json` — a separately curated bank:
atoms carry `level` (expert/middle/basic), `priority` (high/medium/low), and a
`category_hint` ("Group > Sub"), with optional `aliases`/`presentation` and a
`deferred` parking lot — instead of against the live CV. Qualifier-aware
parsing attributes a per-mention level ("Solid experience with X" → expert;
"5+ years of X" → years-based); a bare mention is "no constraint". The live CV
remains the trust gate and the pass-through carrier for non-skill sections.

**Options considered.**

1. *Match against the live CV (status quo).* Rejected: the CV's presentation
   vocabulary is not a canonical match vocabulary, and JD skills the CV does
   not display could never match.
2. *Match against the full bank including `deferred`.* Rejected: deferred is
   the operator's parking lot, not a claimable skill.
3. *Bank-driven with a trust policy (chosen).* Bank atoms are the authoritative
   vocabulary plus level/priority/category metadata; the trust policy drops any
   matched atom whose canonical form is not already vouched for on the live CV,
   and drops low-level atoms below a JD qualifier.

**Decision.** `tailor_cv(jd_text, baseline_atoms, live_cv, *, title="",
threshold=0.8)` in `app/matching/tailor.py` rebuilds the tailored CV's
`skills`/`additional_skills` from matched bank atoms:

- mentions attribute a required level per canonically-normalized atom
  (strongest mention wins; `parser.extract_mentions`);
- the level filter rejects atoms below the requirement
  (`filter_atoms_by_level`, strengths expert 3 / middle 2 / basic 1);
- a bounded fuzzy fallback (`_FUZZY_MAX_TOKENS=300`, `fuzz.partial_ratio` /
  `fuzz.ratio` ≥ 0.8) catches typos and paraphrases with no level constraint —
  words that are (or normalize to) an index key are deliberately skipped, so a
  level-vetted atom can never be smuggled back in through the fuzzy path;
- the trust policy (`_trust_filter`) drops unvouched atoms and logs which ones;
- survivors are grouped by `category_hint` mapping onto the CV skills shape,
  hints under "Additional skills" land in `additional_skills`, and atoms are
  priority-ordered (high → low, stable) within a group;
- all non-skill sections pass through unchanged; `title` optionally overrides.

`POST /cv/tailor` loads the bank lazily via `get_baseline()` (mtime/size-keyed
cache — generation-checked hot reload, the same spirit as `CvSource`), writes
`CV_TAILORED_DIR/cv_tailored-<UTC-ts>.json`, and returns the tailored CV plus
`saved_to`. The MCP `match_jd` tool shares the identical pipeline. Knobs live in
`settings.cv_baseline_path` / `settings.cv_tailored_dir`; auth per ADR-018.

**Consequences.** A JD that matches nothing yields empty skill sections — a
faithful match verdict, not a padded copy of the live CV. The bank validates
loudly (`BaselineError`): schema violations, empty pools, or duplicate atoms
abort the call. Index insertion is canonical-first, so an alias can never
shadow a real atom (e.g. the "API security" atom's "Casbin" alias cannot hijack
the standalone "Casbin" atom). `presentation`/`deferred` are metadata-only
today. The operator's data files (`data/cv.json`, `data/cv_baseline.json`)
remain hand-curated and unchanged by tailoring.

## ADR-020: Multi-subdomain edge via HTTPS Load Balancer + Cloud CDN (Phase 1a)

**Context.** Phase 1 evolves the single Cloud Run service into a multi-subdomain,
multi-service platform (`www.` landing, `app.` private SPA console, `api.`
api-core FastAPI, `games.` api-games). Today a single service is mapped directly
to `ivanprytula.dev` via Cloud Run domain mappings (`scripts/deploy-cloud-run.sh`,
`.local/custom-domain-plan.md`). Growing to four services with host-based routing,
managed TLS, and CDN needs a central edge, and the frozen plan chose a real HTTPS
Load Balancer + Cloud CDN as the gateway.

**Options considered.**

1. *Cloud Run per-service domain mappings (status quo).* Rejected: no central
   URL-map, no CDN, no WAF story; each service needs its own mapping+cert with no
   host-routing to a shared front, and it does not give the interview-value
   edge/gateway vocabulary the plan targets.
2. *Shared symmetric edge cookie / session gateway.* Rejected at the transport
   level: the edge is pure L7 routing; auth is delegated to the API layer
   (Phase 1c), not terminated here.

**Decision.** Manage the edge as Terraform IaC (single managed environment, flat
`terraform/` layout — no per-env split). Modules:

- `modules/cloud_run_service` — one Cloud Run service + its serverless NEG
  (reused by every workload: `api-core`, `api-games`, `spa-origin`, later
  `workers`).
- `modules/edge_lb` — global static IPv4, Google-managed SSL certs (one per
  routed host), serverless backend services bound to the NEGs, an HTTPS URL map
  with one host rule per FQDN, a target HTTPS proxy, the global forwarding rule,
  and optional Cloud CDN-backed backend buckets for static assets.
- `modules/dns` — one Cloud DNS managed zone (`create_dns_zone`, false keeps DNS
  at the current registrar) plus A records for apex + `www`/`api`/`app`/`games`
  → the LB IPv4.

The root composition separates **workloads** (distinct Cloud Run services, keyed
map `services`) from **host routing** (`host_routing`: hostname → workload name)
so two hosts can share one workload — `www.<apex>` **and** `api.<apex>` both
route to `api-core`, preserving the recruiter-critical Jinja landing + `/cv*`
surface on the existing paths. `terraform/terraform.tfvars.example` documents the
shape; real values (`terraform.tfvars`) are gitignored. Remote state targets a
GCS bucket bootstrapped with `just deploy bootstrap-state` (see the
`scripts/deploy-cloud-run.sh` stage): it creates the versioned bucket and runs
`terraform init`, so state storage and locking come up in one step. The GCS
backend locks via an object write-hold in that same bucket — there is no
separate lock bucket (that is an AWS DynamoDB concept) — and bucket versioning
is what makes both locking and crash-safe history work. Pre-commit enforces the
IaC gates: `terraform fmt` (format), `tflint` (logic), and `checkov` (security,
isolated via `uvx` because checkov's `packaging<24.0` pin conflicts with
`fastmcp`'s `>=24.0` in the project venv).

**Consequences.** The LB edge adds ~$47 to the ~79-day GCP budget (frozen plan
estimate), accepted. Google-managed certs are free and auto-renewing; the HTTPS
target proxy requires certs to reach ACTIVE before traffic flows (Terraform
retries; provisioning time depends on DNS). Apex DNS is currently at Squarespace:
`create_dns_zone=true` moves it into Cloud DNS (register the printed
nameservers), `false` requires manually wiring each subdomain's A record to the
printed LB IP — either way the operator action is explicit in the DNS output.
Direct `api-core` developer convenience (`just dev`, no LB) is unaffected; the LB
only fronts deployed traffic. XFF handling behind the LB (`TRUST_PROXY` /
`CLIENT_IP_XFF_ENTRY`, ADR-009/012) must be re-verified against the live LB's
`X-Forwarded-For` chain — flagged as an open risk pending a real deployment.

**Implementation lessons (Phase 1a apply).**

1. *GCP resource name constraints are not validated by `terraform plan`.*
   Google Cloud global LB resources (SSL certificate names, backend service names,
   URL map path-matcher names, managed DNS zone names) must match RFC 1035:
   `^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$` — letters, digits, hyphens only;
   no dots. `terraform plan` produces no warning. The first `apply` that creates
   any of these resources fails with a GCP API rejection. The fix is
   `lower(replace(hostname, ".", "-"))` applied consistently at every name
   assignment (7 sites in `edge_lb` alone). A future pre-apply check (e.g. a
   checkov custom check or `terraform validate` plugin) should catch this before
   the first apply.

2. *DNS zone names differ from record set names.* The managed zone `name`
   argument is the DNS zone apex (e.g. `ivanprytula.dev.` with trailing dot).
   Using `replace(zone_name, ".", "-")` produces a trailing hyphen
   (`ivanprytula-dev-`) because the trailing dot is also replaced. Fix: strip
   the trailing dot first with `trimsuffix(var.dns_name, ".")` before replacing
   remaining dots.

3. *GCS backend state lock.* Interrupted `terraform apply` runs can leave a
   lock on the GCS state bucket. The lock auto-releases after the lock timeout
   (typically 10 minutes), but during development `--lock=false` bypasses it.
   In CI, ensure apply steps are not interrupted; in manual运维, use `terraform
   force-unlock <lock-id>` if the timeout is too long.

4. *SPA-origin service account in tfvars.* The runtime SA email for the
   `spa-origin` workload must be a plain email address
   (`cv-ivanprytula-runtime@<project>.iam.gserviceaccount.com`), not a gcloud
   CLI command string. A corrupted tfvars entry silently creates the wrong
   identity or breaks the apply.

## ADR-021: Cloud CDN static assets + private signed-URL upload bucket (Phase 1b)

**Context.** Phase 1b puts real static content (large images, JS, audio/video) on
the edge to exercise Cloud CDN, and later adds a UI file-upload feature (user
profile avatars/photos behind auth-protected APIs). Two distinct access models are
needed: **public-but-CDN-served** static assets, and **fully private** user
content. Phase 1a's `edge_lb` routed whole hosts to a bucket; that is too blunt.

**Options considered.**

1. *Whole-host static bucket (`static.<apex>` → bucket).* Rejected: a host is
   either all-container or all-bucket; you cannot split `/assets/*` out of `app.`
   while keeping the SPA on the container, which is the pattern that actually
   shows CDN value.
2. *Same bucket for CDN origin and user uploads.* Rejected: user content must be
   private and versioned; a CDN origin must be publicly readable. Mixing them
   forces a single (public or private) posture onto both, and couples CDN cache
   invalidation to user writes. Two buckets keeps each policy clean.
3. *Anonymous write to a private bucket.* Rejected outright — writes are
   signed-URL-only, never public.

**Decision.**

- **CDN via prefix routing inside a host.** `edge_lb` accepts a `path_routes` map
  (`host → {prefix, bucket}`) and emits a URL-map `path_rule` on that host's
  path-matcher: e.g. `app.<apex>/assets/*` → Cloud CDN backend bucket, while
  `app.<apex>/` stays on the `spa-origin` container. Bucket served with
  `enable_cdn=true`, `cache_mode="CACHE_ALL_STATIC"`.
- **`modules/static_bucket`** creates the GCS origin for the CDN. It is the **one
  deliberate public-read exception** (`allUsers objectViewer`), because that is
  how a `google_compute_backend_bucket` origin works; `public_access_prevention`
  must stay off and CKV_GCP_28/114/62 are skipped for it. Versioning is on (real
  fix), plus CORS for the SPA.
- **Deny-public is the default for every other bucket.** The guarantee is
  enforced by a dedicated path-scoped guard, `scripts/ensure_deny_public.py`,
  because checkov cannot express it: its `skip-check` is global (it cannot
  skip only the CDN origin) and its inline `#checkov:skip` is unreliable in the
  pinned version (measured: "Skipped checks: 0"). The guard fails if any
  non-origin bucket lacks `public_access_prevention="enforced"` + uniform access,
  or if any bucket binds an anonymous **write** role. It runs as its own
  pre-commit hook; checkov gets `--skip-check CKV_GCP_62,CKV_GCP_114,CKV_GCP_28`
  so it only enforces the CDN-exception-free checks.
- **`modules/uploads`** is a private user-content bucket (enforced deny-public,
  uniform access, versioning, no public IAM). Writes and reads are **V4 signed
  URLs** generated server-side from the app service account: the UI PUTs to a
  short-TTL, object-scoped upload URL and later GETs a signed read URL from an
  auth-protected endpoint. Object keys are `user_id`-scoped
  (`{prefix}/{user_id}/{uuid}.ext`) so users cannot enumerate each other. The
  uploads module is **committed but commented out** in the root config: the
  operator is practicing `tf plan`/`apply` cycles on the CDN piece first and will
  uncomment the module + variable together when ready.

**Consequences.** `static.<apex>` whole-host wiring is replaced by an `app.<apex>`
`/assets/*` prefix (terraform.tfvars.example updated). Index.html must reference
assets with that prefix so they hit the CDN. A CI gate (the guard + tests in
`tests/test_deny_public.py`) now proves the "no public write, no un-enforced
bucket" invariant, which is the permission surface the later upload UI depends
on. The CDN origin is an explicit, allowlisted exception — a future reviewer
adding another public bucket will get a hard failure until they justify and
allowlist it.
