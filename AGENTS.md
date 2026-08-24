# AGENTS.md

## Python Environment

Requires Python 3.14+.

All dependencies are project-specific and managed by `uv`. Install with:

```bash
uv sync --extra dev
```

When running Python commands, use `uv run` to execute within the project virtual environment, or activate it manually:

```bash
uv run <command>

# or
source .venv/bin/activate
```

## Code Style

- Follow existing FastAPI + FastMCP patterns in `app/main.py`
- Use `ruff` for linting and formatting
- Use `ty` for type checking

## Commands

```bash
just dev                  # run dev server with hot reload
just code-quality         # ruff check + ruff format + ty type check
just test                 # run test suite with coverage (extra args pass through)
```

Note: `set dotenv-load` injects `.env` into every just recipe (dev server gets CONTACT_NAME/CONTACT_EMAIL etc.). A manually started uvicorn does NOT read `.env` — source it (`set -a; source .env; set +a`) or Swagger metadata stays empty.

## Project

FastAPI + FastMCP CV rendering service. PDFs via WeasyPrint. Templates in `templates/`, themes in `app/themes/`.

## Codebase Map

```text
app/
├── main.py              # FastAPI app assembly, MCP tools, lifespan, /mcp mount
├── constants.py         # Project paths (TEMPLATE_DIR, THEMES_DIR), cache/worker limits
├── routes.py            # REST endpoints: /, /health, /cv, /cv/html, /cv/preview, /cv/pdf
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
└── cv.json              # CV content (validated against CVData model)

config/
└── blocked_geo.txt      # GENERATED geo blocklist (ipdeny RU IR KP BY CU SY VE MM) — refresh: just update-geo-blocklist

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
└── test_consent.py      # GDPR/RODO recruiter-clause tests (HTML/preview/PDF cache)

docs/
├── architecture.md      # System components, data flow, endpoints
├── design.md            # Design principles, patterns, constraints
└── decisions.md         # ADR-style decision log

Dockerfile              # Production container image
.editorconfig           # Editor defaults: Ruff mirror for Python, web-standard indents
justfile                # Recipes: setup, dev, code-quality, test, test-pdf, build, run, gcloud-build, mcp-*
pyproject.toml          # Python 3.14+, deps, ruff/ty config, pytest asyncio_mode=auto
```

### Key Patterns

- **Theme contract**: `app/themes/__init__.py` defines `Theme` Protocol requiring `CSS: str`. Theme modules validated at import time via `isinstance(module, Theme)`.
- **Theme styling scope**: themes set ONLY fonts/sizes/colors; structure (list markup, list-style, geometry, fallbacks) lives in `cv_base.html` as zero-specificity `:where()` defaults so theme overrides win regardless of stylesheet order (`{{css}}` is injected BEFORE the base block).
- **Semantic markup + running-element gotcha**: cv_base.html uses HTML5 semantics (`main`/`header`/`address`/`article`/`h3`/`time`/`footer`) with classes as styling hooks; UA defaults are neutralized via `:where(address)/:where(h3)` resets. The `.cv-footer` running element MUST stay first in `<body>`: CSS GCPM makes a running element available to margin boxes only from its document page onward, so moving it to the end silently drops footers from all but the last page.
- **PDF visual verification**: when measuring generated PDFs with pdfplumber, check EVERY page and EVERY glyph variant — WeasyPrint's UA stylesheet adds native list markers (duplicate small bullets) unless `list-style: none`, and abs-pos offsets anchor to the padding box. Page-1-only checks have shipped real bugs (overlapped/duplicated bullets in the original theme).
- **PDF cache**: LRU-bounded (50 entries) `OrderedDict` keyed by `(theme, sha256(cv_json + consent-tag))` — the recruiter GDPR/RODO clause (`consent`/`company` query params) is part of the key, so different companies never share cached PDFs. Shared `_get_or_render_pdf()` helper for sync/async paths.
- **PDF functions**: `generate_cv_pdf(theme, cv_json)` and `generate_cv_pdf_async(theme, cv_json)` both require explicit `cv_json` dict — no module-level state.
- **Rate limiting**: slowapi `Limiter` keyed by `get_client_ip` (XFF-entry / header / socket-peer strategies). REST uses the `@limits(...)` stacked decorator (burst + sustained, loopback-socket-peer exempt); MCP tools enforce via `app/mcp_limits.py` stubs + `get_http_request()`. `GuardMiddleware` (added last = runs first) handles allowlist/blocklist/dynamic bans/service hours; `/health` always passes. Loopback exemptions (limits, failban) are gated by `TRUST_PROXY`: proxied platforms (Cloud Run peer = 127.0.0.1 for everyone) MUST set `TRUST_PROXY=true` + `CLIENT_IP_XFF_ENTRY=2` or limits silently stop applying.
- **IP access lists**: `parse_ip_list` accepts commas, whitespace, and newlines; `#` comments run to end of line (stripped BEFORE comma splitting — a comma inside a comment must not split tokens). Inline env values merge with `*_FILE` files; missing configured file = startup failure. Large geo lists MUST use the file form (execve caps env args at ~128KB); regenerate via `just update-geo-blocklist`.
- **Image packaging**: the image ships `data/cv.example.json` ONLY (never real cv.json — CV content comes from GCS via `CV_DATA_GCS_URI`) plus `config/` (geo blocklist). `.dockerignore` and `.gcloudignore` both use `data/*` + `!data/cv.example.json`; gcloud builds submit applies `.gcloudignore` verbatim when present, otherwise it derives one from `.gitignore`, which excludes personal data.
- **MCP tools**: Return base64 string for `generate_cv_pdf_tool` (MCP is JSON-only). Re-raises `ToolError` without wrapping.
- **Tests**: Use `httpx.AsyncClient` + `ASGITransport` with `asyncio_mode = "auto"` — async tests need no `@pytest.mark.asyncio` marker.
- **Tests are CV-data-independent**: tests must NOT assert on `data/cv.json` wording, names, or counts (the file is user content that changes often). Use the `SYNTHETIC_CV` fixtures from `tests/conftest.py` (`synthetic_cv`, `synthetic_cv_path`, `pdf_service`, `override_pdf_service`). Only structural smoke checks (e.g., "experience is a list") are allowed against the real file.
- **Chrome DevTools MCP privacy**: NEVER attach to or enumerate the user's real browser window/tabs. Always open test pages with `isolatedContext` set (incognito-equivalent) and close them when done.

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

6. **Docs sync.** When architecture, design, or ADRs change, update `docs/architecture.md`, `docs/design.md`, or `docs/decisions.md` respectively. Do not leave implementation drift between code and docs.
