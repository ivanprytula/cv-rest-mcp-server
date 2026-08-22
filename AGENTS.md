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
just lint                 # lint
just format               # format
just typecheck            # type check
just test                 # run test suite
```

## Project

FastAPI + FastMCP CV rendering service. PDFs via WeasyPrint. Templates in `templates/`, themes in `app/themes/`.

## Codebase Map

```text
app/
├── main.py              # FastAPI app, MCP tools, REST endpoints mounted at /mcp
├── cv_data.py           # Pydantic models (CVData, Experience, Education), loads data/cv.json
├── pdf_generator.py     # Theme loading, PDF caching, sync/async WeasyPrint generation
├── rate_limiter.py      # IPRateLimiter: 5 req/15min per IP, localhost exempt
├── renderer.py          # Jinja2 HTML rendering using templates/cv_base.html
└── themes/
    ├── __init__.py      # Theme Protocol definition
    ├── classic.py       # THEME_NAME + CSS string
    ├── minimal.py       # THEME_NAME + CSS string
    └── modern.py        # THEME_NAME + CSS string

templates/
└── cv_base.html         # Base Jinja2 template (replaces {{css}}, {{name}}, etc.)

data/
└── cv.json              # CV content (validated against CVData model on import)

tests/
├── conftest.py          # AsyncClient fixture via ASGITransport
├── test_api.py          # REST endpoint tests
├── test_cv_data.py      # Data validation tests
├── test_mcp.py          # MCP tool tests
├── test_pdf_generator.py # PDF generation tests
└── test_rate_limiter.py # Rate limiter tests

Dockerfile              # Production container image
justfile                # Recipes: setup, dev, lint, format, typecheck, test, build, run, gcloud-build
pyproject.toml          # Python 3.14+, deps, ruff/ty config, pytest asyncio_mode=auto
```

### Key Patterns

- **Theme contract**: `app/themes/__init__.py` defines `Theme` Protocol requiring `CSS: str`. Theme modules validated at import time via `isinstance(module, Theme)`.
- **PDF cache**: LRU-bounded (50 entries) `OrderedDict` keyed by `(theme, sha256(cv_json))`. Shared `_get_or_render_pdf()` helper for sync/async paths.
- **PDF functions**: `generate_cv_pdf(theme, cv_json)` and `generate_cv_pdf_async(theme, cv_json)` both require explicit `cv_json` dict — no module-level state.
- **Rate limiting**: slowapi `Limiter` with `get_remote_address` key func. Wired via `SlowAPIMiddleware` + per-endpoint `@limiter.limit()` decorators.
- **MCP tools**: Return base64 string for `generate_cv_pdf_tool` (MCP is JSON-only). Re-raises `ToolError` without wrapping.
- **Tests**: Use `httpx.AsyncClient` + `ASGITransport` with `asyncio_mode = "auto"`.

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
