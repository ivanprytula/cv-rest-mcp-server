# REST API Contract

This is the explicit contract for the HTTP API of the CV REST/MCP Server.
The schemas below are generated into the interactive Swagger UI at `/docs`
from code; this document is the readable form of that contract.

## Conventions

- **Base URL**: the deployed origin behind the HTTPS Load Balancer (Phase 1a).
  Hosts: `https://api.<apex>` (api-core), `https://www.<apex>` (Jinja landing,
  same api-core workload), `https://app.<apex>` (private React SPA), and
  `https://games.<apex>` (api-games). Local dev: `http://localhost:8000`.
- **Versioning**: current REST surface is unversioned (paths under `/cv`,
  `/api`, `/health`) and — per Phase 1a — **kept on the same paths** regardless
  of which subdomain front them, so recruiter links and `config/mcp_clients.json`
  base URLs keep working. New auth/SPA endpoints arrive as `/api/v1/*` (Phase 1c).
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
  The private console auth lives under `/api/v1/auth/*` (see the Auth section
  below).
- **Infra**: `GET /health` is exempt from access gate and rate limits.

## Status codes

<!-- markdownlint-disable MD060 -->
| Code | Meaning                                                                                          | Typical source                                                   |
| ---- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| 200  | Success (JSON document or rendered representation)                                               | all endpoints                                                    |
| 401  | Missing/malformed `Authorization` header, or invalid token                                       | `POST /cv/tailor`; `?tailored=` reads                            |
| 404  | Unknown theme, or tailored revision not found                                                    | `/cv/html`, `/cv/pdf`, `/cv/preview`                             |
| 413  | JD body exceeds the 10 MB payload cap                                                            | `POST /cv/tailor`                                                |
| 422  | Malformed/empty JD body, or FastAPI query-param validation                                       | `/cv/*`, `/cv/tailor`                                            |
| 429  | Rate limit exceeded (see table below)                                                            | all endpoints                                                    |
| 500  | Unexpected internal error (sanitized; no internals leaked)                                       | `POST /cv/tailor`                                                |
| 503  | CV source / PDF service not initialized; **or** tailor endpoint requested without a bearer token | `/cv*` (via `Depends`); `/cv/tailor` + `?tailored=` reads (auth) |
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

| Item         | Value                                                                                                                                                                                                                                     |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Content-Type | `text/html; charset=utf-8`                                                                                                                                                                                                                |
| Query params | `theme` (default `classic`), `company`, `consent`, `tailored`                                                                                                                                                                             |
| Params notes | `company` is whitespace-collapsed and **truncated to 120 chars**; non-empty `company` implies `consent=true`. `tailored` (requires auth) is a bare `cv_tailored-<ts>.json` revision name or `latest` — see "Reading a tailored revision". |
| Success      | `200` — themed CV HTML                                                                                                                                                                                                                    |
| Errors       | `401`, `404` (unknown theme / revision), `422` (bad query params), `429`, `503`                                                                                                                                                           |

```bash
curl -s "https://<origin>/cv/html?theme=minimal" -o cv.html
```

---

### `GET /cv/preview`

Interactive toolbar page embedding `/cv/html` in an iframe (human UI).

| Item         | Value                                                                                     |
| ------------ | ----------------------------------------------------------------------------------------- |
| Content-Type | `text/html`                                                                               |
| Query params | as `/cv/html`; forwarded to the embedded frame and download button (incl. auth `?token=`) |
| Errors       | `401`, `404`, `429`, `503`                                                                |

---

### `GET /cv/pdf`

Downloadable PDF, attachment via `Content-Disposition`.

| Item         | Value                                                                                                |
| ------------ | ---------------------------------------------------------------------------------------------------- |
| Content-Type | `application/pdf`                                                                                    |
| Headers      | `Content-Disposition: attachment; filename="CV_<name>_<title>_<ts>.pdf"`                             |
| Query params | as `/cv/html` (theme/company/consent/`tailored`)                                                     |
| Success      | `200` — PDF bytes (single page + optional last-page GDPR/RODO consent clause, part of the cache key) |
| Errors       | `401`, `404` (unknown theme / revision), `422`, `429`, `503`                                         |

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
| Item    | Value                                                                                                                                                                 |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Success | `200` — tailored CV object: same shape as `/cv` with `skills`/`additional_skills` rebuilt from matched bank atoms, plus `saved_to` (`cv_tailored-<UTC-ts>.json` path) |
| Errors  | `401`, `413`, `422`, `429`, `500`, `503` (see below)                                                                                                                  |
<!-- markdownlint-enable MD060 -->

**Error details for `POST /cv/tailor`:**

- `401 Unauthorized` — missing `Authorization` header, malformed header (anything
  other than `Bearer <token>`), or invalid token. Every 401 response carries
  `WWW-Authenticate: Bearer` so clients know the required scheme. The token is
  a JWT issued by `POST /api/v1/auth/token` (operator login); the access token
  must carry `role=admin`. The signing key is `JWT_SIGNING_KEY` (HS256,
  Secret Manager in production). The presented token is never logged.
- `403 Forbidden` — token is valid but does not carry the required `admin` role.
- `413 Payload Too Large` — body exceeds the 10 MB cap.
- `422 Unprocessable Entity` — malformed JSON, corrupt/undecodable PDF/DOCX, or
  empty `jd_text`.
- `429 Too Many Requests` — rate limit exceeded (see table above).
- `500 Internal Server Error` — unexpected tailoring failure (sanitized; no
  internals leaked), or the skill bank is missing/malformed (a broken bank aborts
  the call loudly instead of emitting an empty skills section).
- `503 Service Unavailable` — either the CV source / PDF service is not
  initialized, **or** `JWT_SIGNING_KEY` is not configured (the endpoint is
  fail-closed; this is intentional, not an outage).

```bash
# raw text (admin JWT required)
TOKEN="$(curl -s -X POST https://<origin>/api/v1/auth/token \
  -H 'content-type: application/json' \
  -d '{"username":"operator","password":"..."}' | jq -r .access_token)"
curl -s -X POST "https://<origin>/cv/tailor" \
  -H "authorization: Bearer $TOKEN" \
  -H "content-type: text/plain" --data-binary @jd.txt

# JSON
curl -s -X POST "https://<origin>/cv/tailor" \
  -H "authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{"jd_text": "Required: Python, FastAPI", "title": ""}'

# PDF / DOCX
curl -s -X POST "https://<origin>/cv/tailor" \
  -H "authorization: Bearer $TOKEN" \
  -H "content-type: application/pdf" --data-binary @jd.pdf
```

### Reading a tailored revision

Tailored revisions written by `POST /cv/tailor` can be rendered with the same
three read endpoints by passing `tailored`:

- `tailored=<name>` — the bare `cv_tailored-<UTC-ts>.json` filename returned in
  `saved_to` (e.g. `cv_tailored-2026-08-29_10-00-00.json`), or
- `tailored=latest` — the most recently written revision.

Because revisions can contain JD-derived content, these calls are gated by the
same JWT flow as the mutation route (the `?tailored=` selector requires the
`cv:read` scope — both admin and any future user roles have it). Use the
Authorization header for scripts, or `?token=` when the request comes from a
browser iframe (the `/cv/preview` toolbar does this for you). `tailored` only
names a `.json` file directly inside the revisions dir — path separators are
rejected with `404`, so no traversal beyond that dir is possible.

```bash
# render the latest revision as HTML/PDF/preview (header auth)
curl -s "https://<origin>/cv/pdf?theme=minimal&tailored=latest" \
  -H "authorization: Bearer $TOKEN" -o tailored.pdf

# preview page for a specific revision (query auth for the embedded iframe)
open "https://<origin>/cv/preview?theme=classic&tailored=cv_tailored-2026-08-29_10-00-00.json&token=$TOKEN"
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

---

## Auth (`/api/v1/auth/*`)

Private operator console auth (Phase 1c, ADR-022). Transport: the **access
token** is returned in the JSON body and must be sent as
`Authorization: Bearer <token>`; the **refresh token** is an `__Host-` httpOnly,
Secure, SameSite=None cookie (`Path=/`) consumed only by
`POST /api/v1/auth/refresh`.

The `/api/v1/*` namespace is gated by `JWTAuthMiddleware`; login, refresh, and
logout are the three endpoints exempted (they carry their own credential). Every
401 carries `WWW-Authenticate: Bearer`.

### `POST /api/v1/auth/token` (login)

Classic username + password login for the single operator.

| Item         | Value                                                                                          |
| ------------ | ---------------------------------------------------------------------------------------------- |
| Content-Type | `application/json`                                                                             |
| Body         | `{"username": "operator", "password": "<operator password>"}`                                 |
| Success      | `200` — `TokenPair`: `{access_token, token_type, expires_in}`; sets the `__Host-refresh_token` cookie |
| Errors       | `401` (invalid username or password — same generic message for both, so the accepted username is never revealed), `422` |

Fail-closed: with no user in the store (no `FIRST_ADMIN_*` seed at startup,
ADR-022 Phase 2), login returns `401` with a generic `Invalid credentials` — it
never reveals whether auth is configured.

```bash
curl -s -X POST "https://api.<apex>/api/v1/auth/token" \
  -H "content-type: application/json" \
  -d '{"username":"operator","password":"$OPERATOR_PASSWORD"}' \
  -c cookies.txt
```

### `POST /api/v1/auth/refresh`

Rotate the refresh token and issue a new access token. Reads the `__Host-`
httpOnly cookie (same-origin or the pinned SPA origin via credentialed CORS).

| Item        | Value                                                                                          |
| ----------- | ---------------------------------------------------------------------------------------------- |
| Credentials | `__Host-refresh_token` cookie (required)                                                       |
| Success     | `200` — new `TokenPair`; a **rotated** refresh cookie is set                                      |
| Errors      | `401` (missing cookie, unknown token, or **replay** — reusing a rotated token revokes the whole family) |

Replay detection: presenting a previously-rotated refresh token revokes the
entire token family; subsequent refreshes with any token in that family return
`401`.

```bash
curl -s -X POST "https://api.<apex>/api/v1/auth/refresh" \
  -b cookies.txt -c cookies.txt
```

### `POST /api/v1/auth/logout`

Revoke the refresh-token family and clear the cookie.

| Item        | Value                                       |
| ----------- | ------------------------------------------- |
| Credentials | `__Host-refresh_token` cookie (optional)    |
| Success     | `204` (cookie cleared; family revoked)      |
| Errors      | none                                        |

### `GET /api/v1/auth/me`

Return the operator identity + scopes from a valid access token.

| Item        | Value                                                                    |
| ----------- | ------------------------------------------------------------------------ |
| Credentials | `Authorization: Bearer <access_token>` (required)                        |
| Success     | `{"subject": "operator", "scopes": ["cv:read", "cv:manage"]}`            |
| Errors      | `401` (missing/invalid/expired token), `503` (auth unconfigured)         |
