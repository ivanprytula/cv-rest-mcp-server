# REST API Contract

This is the explicit contract for the HTTP API of the CV REST/MCP Server.
The schemas below are generated into the interactive Swagger UI at `/docs`
from code; this document is the readable form of that contract.

## Conventions

- **Base URL**: the deployed origin (GCP Cloud Run). Local dev: `http://localhost:8000`.
- **Versioning**: current API is unversioned (paths under `/cv`, `/api`, `/health`).
- **Errors**: every non-2xx response is JSON `{"detail": "<message>"}` — a single
  `detail` string. FastAPI's automatic validation errors are the exception and
  also carry `detail`.
- **Machine API vs. UI pages**: `/cv`, `/cv/html`, `/cv/pdf`, `/cv/tailor`,
  `/api/games/...` are the machine API. `/`, `/cv/preview`, `/culture-bingo`
  are HTML pages for humans and outside the contract's code guarantees.
- **Auth**: `POST /cv/tailor` and the `?tailored=` revision reads (`/cv/html`,
  `/cv/preview`, `/cv/pdf`) require `Authorization: Bearer <token>`. The three
  revision reads additionally accept the token as a `?token=` query parameter
  (a browser iframe cannot send an Authorization header); the mutation route is
  header-only. Every 401 carries `WWW-Authenticate: Bearer`. All other endpoints
  are unauthenticated; `CORS` is public-read (wildcard origin, no credentials).
- **Infra**: `GET /health` is exempt from access gate and rate limits.

## Status codes

<!-- markdownlint-disable MD060 -->
| Code | Meaning                                                                                            | Typical source                                                  |
| ---- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 200  | Success (JSON document or rendered representation)                                                 | all endpoints                                                   |
| 401  | Missing/malformed `Authorization` header, or invalid token                                         | `POST /cv/tailor`; `?tailored=` reads                              |
| 404  | Unknown theme, or tailored revision not found                                                     | `/cv/html`, `/cv/pdf`, `/cv/preview`                            |
| 413  | JD body exceeds the 10 MB payload cap                                                              | `POST /cv/tailor`                                               |
| 422  | Malformed/empty JD body, or FastAPI query-param validation                                         | `/cv/*`, `/cv/tailor`                                           |
| 429  | Rate limit exceeded (see table below)                                                              | all endpoints                                                   |
| 500  | Unexpected internal error (sanitized; no internals leaked)                                         | `POST /cv/tailor`                                               |
| 503  | CV source / PDF service not initialized; **or** tailor endpoint requested without a bearer token   | `/cv*` (via `Depends`); `/cv/tailor` + `?tailored=` reads (auth) |
<!-- markdownlint-enable MD060 -->

## Rate limits

Limits are stacked (burst + sustained); breaches return `429`.

| Endpoint                           | Burst    | Sustained |
| ---------------------------------- | -------- | --------- |
| `/`                                | 30/min   | 120/hour  |
| `/health`                          | 60/min   | —         |
| `/cv`, `/cv/html`, `/cv/preview`   | 30/min   | 300/hour  |
| `/cv/pdf`                          | 5/15 min | 15/hour   |
| `/cv/tailor`                       | 10/min   | 60/hour   |
| `/culture-bingo`, `/api/games/...` | 30/min   | 120/hour  |
| MCP read tools                     | 30/min   | 240/hour  |
| MCP `generate_cv_pdf_tool`         | 5/15 min | 15/hour   |

## Endpoints

### `GET /cv`

Raw CV document as it is served to renderers.

| Item         | Value                                          |
| ------------ | ---------------------------------------------- |
| Content-Type | `application/json`                             |
| Params       | none                                           |
| Success      | `200` — CV object (schema in `app/cv_data.py`) |
| Errors       | `429`, `503`                                   |

```bash
curl -s https://<origin>/cv | jq '.name, .title'
```

---

### `GET /cv/html`

Rendered CV page (HTML, no toolbar chrome).

| Item         | Value                                                                                                         |
| ------------ | ------------------------------------------------------------------------------------------------------------- |
| Content-Type | `text/html; charset=utf-8`                                                                                    |
| Query params | `theme` (default `classic`), `company`, `consent`, `tailored`                                                 |
| Params notes | `company` is whitespace-collapsed and **truncated to 120 chars**; non-empty `company` implies `consent=true`. `tailored` (requires auth) is a bare `cv_tailored-<ts>.json` revision name or `latest` — see "Reading a tailored revision". |
| Success      | `200` — themed CV HTML                                                                                        |
| Errors       | `401`, `404` (unknown theme / revision), `422` (bad query params), `429`, `503`                               |

```bash
curl -s "https://<origin>/cv/html?theme=minimal" -o cv.html
```

---

### `GET /cv/preview`

Interactive toolbar page embedding `/cv/html` in an iframe (human UI).

| Item         | Value                                                              |
| ------------ | ------------------------------------------------------------------ |
| Content-Type | `text/html`                                                        |
| Query params | as `/cv/html`; forwarded to the embedded frame and download button (incl. auth `?token=`) |
| Errors       | `401`, `404`, `429`, `503`                                                                  |

---

### `GET /cv/pdf`

Downloadable PDF, attachment via `Content-Disposition`.

| Item         | Value                                                                                                |
| ------------ | ---------------------------------------------------------------------------------------------------- |
| Content-Type | `application/pdf`                                                                                    |
| Headers      | `Content-Disposition: attachment; filename="CV_<name>_<title>_<ts>.pdf"`                             |
| Query params | as `/cv/html` (theme/company/consent/`tailored`)                                                      |
| Success      | `200` — PDF bytes (single page + optional last-page GDPR/RODO consent clause, part of the cache key) |
| Errors       | `401`, `404` (unknown theme / revision), `422`, `429`, `503`                                          |

---

### `POST /cv/tailor`

Match a job description against the **skill bank** (`data/cv_baseline.json`) and
return a tailored CV. Skills are **rebuilt** from bank atoms, not reordered from
the live CV: JD qualifiers ("Solid experience with X" → expert, "5+ years of X" →
years-based) filter atoms by level; the **trust policy** drops any matched atom
that is not already vouched for on the live CV; survivors are grouped by the
atom's `category_hint` (priority-ordered within a group). A JD that matches
nothing yields **empty** skill sections. Every success also writes a
`cv_tailored-<UTC-ts>.json` revision into `CV_TAILORED_DIR` and returns its path
as `saved_to`. Non-skill sections (experience, summary, education, …) pass
through unchanged.

**Request body** — raw bytes, max **10 MB** (`text/plain` in Swagger; any
Content-Type works). Format is chosen by:

1. Explicit `Content-Type` (see table), then
2. magic-byte sniffing for generic/unknown types (blanks, `application/octet-stream`,
   `application/binary`, `*/*`) — `%PDF` → PDF, `PK\x03\x04` → DOCX, then
3. everything else is read as raw UTF-8 text (JDs pasted into `curl --data-binary`
   need no header).

| Content-Type                          | Format                            |
| ------------------------------------- | --------------------------------- |
| `application/json`                    | `{"jd_text": "...", "title": ""}` |
| `application/pdf`                     | PDF bytes (`pypdf`)               |
| `...wordprocessingml.document` (DOCX) | ZIP bytes (`python-docx`)         |
| `text/plain`, `.txt`                  | JD raw text                       |
| `text/markdown`, `text/x-markdown`    | JD raw text, syntax kept          |

`.doc` (legacy binary) is intentionally not supported.

**Query params**: `title` — overrides the CV title (a `title` inside the JSON
payload wins for the JSON format).

<!-- markdownlint-disable MD060 -->
| Item    | Value                                                                                                                                                 |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Success | `200` — tailored CV object: same shape as `/cv` with `skills`/`additional_skills` rebuilt from matched bank atoms, plus `saved_to` (`cv_tailored-<UTC-ts>.json` path) |
| Errors  | `401`, `413`, `422`, `429`, `500`, `503` (see below)                                                                                                |
<!-- markdownlint-enable MD060 -->

**Error details for `POST /cv/tailor`:**

- `401 Unauthorized` — missing `Authorization` header, malformed header (anything
  other than `Bearer <token>`), or invalid token. Every 401 response carries
  `WWW-Authenticate: Bearer` so clients know the required scheme. The token is
  configured via `TAILOR_BEARER_TOKEN` (inline, dev) or `TAILOR_BEARER_TOKEN_FILE`
  (one-line file, production). Comparison is constant-time via `secrets.compare_digest`;
  the token is never logged.
- `413 Payload Too Large` — body exceeds the 10 MB cap.
- `422 Unprocessable Entity` — malformed JSON, corrupt/undecodable PDF/DOCX, or
  empty `jd_text`.
- `429 Too Many Requests` — rate limit exceeded (see table above).
- `500 Internal Server Error` — unexpected tailoring failure (sanitized; no
  internals leaked), or the skill bank is missing/malformed (a broken bank aborts
  the call loudly instead of emitting an empty skills section).
- `503 Service Unavailable` — either the CV source / PDF service is not
  initialized, **or** `TAILOR_BEARER_TOKEN` is not configured (the endpoint is
  fail-closed; this is intentional, not an outage).

```bash
# raw text (bearer token required)
curl -s -X POST "https://<origin>/cv/tailor" \
  -H "authorization: Bearer $TAILOR_BEARER_TOKEN" \
  -H "content-type: text/plain" --data-binary @jd.txt

# JSON
curl -s -X POST "https://<origin>/cv/tailor" \
  -H "authorization: Bearer $TAILOR_BEARER_TOKEN" \
  -H "content-type: application/json" \
  -d '{"jd_text": "Required: Python, FastAPI", "title": ""}'

# PDF / DOCX
curl -s -X POST "https://<origin>/cv/tailor" \
  -H "authorization: Bearer $TAILOR_BEARER_TOKEN" \
  -H "content-type: application/pdf" --data-binary @jd.pdf
```

### Reading a tailored revision

Tailored revisions written by `POST /cv/tailor` can be rendered with the same
three read endpoints by passing `tailored`:

- `tailored=<name>` — the bare `cv_tailored-<UTC-ts>.json` filename returned in
  `saved_to` (e.g. `cv_tailored-2026-08-29_10-00-00.json`), or
- `tailored=latest` — the most recently written revision.

Because revisions can contain JD-derived content, these calls are Bearer-gated
like the mutation route (fail-closed `503` when `TAILOR_BEARER_TOKEN` is unset).
Use the Authorization header for scripts, or `?token=` when the request comes
from a browser iframe (the `/cv/preview` toolbar does this for you). `tailored`
only names a `.json` file directly inside the revisions dir — path separators
are rejected with `404`, so no traversal beyond that dir is possible.

```bash
# render the latest revision as HTML/PDF/preview (header auth)
curl -s "https://<origin>/cv/pdf?theme=minimal&tailored=latest" \
  -H "authorization: Bearer $TAILOR_BEARER_TOKEN" -o tailored.pdf

# preview page for a specific revision (query auth for the embedded iframe)
open "https://<origin>/cv/preview?theme=classic&tailored=cv_tailored-2026-08-29_10-00-00.json&token=$TAILOR_BEARER_TOKEN"
```

---

### `GET /api/games/culture-bingo/content`

Company Culture Bingo tile content (machine-readable game data).

| Item         | Value                                                   |
| ------------ | ------------------------------------------------------- |
| Content-Type | `application/json`                                      |
| Success      | `200` — bingo object (`{"title": ..., "cells": [...]}`) |
| Errors       | `429`                                                   |

---

### `GET /health`

Liveness / source probe (bypasses access control and limits).

| Item    | Value                                                                                  |
| ------- | -------------------------------------------------------------------------------------- |
| Success | `200` — `{"status": "ok", "cv_source": "file" \| "gcs" \| "placeholder" \| "unknown"}` |
| Errors  | none                                                                                   |
