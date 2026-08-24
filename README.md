# CV REST/MCP Server

FastAPI + FastMCP service that renders a CV as JSON or themed PDFs.

## Run

```bash
just setup && just dev
```

Server: `http://localhost:8080` · MCP: `/mcp` (JSON-RPC, not a browser page)

## REST API

| Method | Path                    | Description                                  |
| ------ | ----------------------- | -------------------------------------------- |
| GET    | `/`                     | Landing page                                 |
| GET    | `/health`               | Health check                                 |
| GET    | `/cv`                   | CV as JSON                                   |
| GET    | `/cv/html?theme=<name>` | Rendered CV as HTML                          |
| GET    | `/cv/preview?theme=<name>` | Preview page with toolbar                 |
| GET    | `/cv/pdf?theme=<name>`  | CV as PDF (attachment)                       |

Interactive OpenAPI docs (Swagger UI): [`/docs`](http://localhost:8080/docs)

## MCP

Mounted at `/mcp` via Streamable HTTP transport.

### Tools

| Tool                   | Parameters   | Returns                       |
| ---------------------- | ------------ | ----------------------------- |
| `get_cv`               | —            | JSON object with full CV data |
| `get_available_themes` | —            | `list[str]` of theme names    |
| `generate_cv_pdf`      | `theme: str` | Base64-encoded PDF bytes      |

### Connect from an MCP client

Any MCP-compatible client (Claude Desktop, Cursor, VS Code with Kilo, Windsurf) can use this server. Add to your client's MCP config:

```json
{
  "mcpServers": {
    "cv-rest-mcp-server": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

For a deployed instance, replace the URL with your public endpoint.

## Themes

`classic` · `minimal` · `modern` · `original` — defined in `app/themes/<name>.py` as `CSS` strings.

## Content & Customization

Edit `data/cv.json` (validated against `CVData` in `app/cv_data.py`). Restart after changes.

Set `CV_DATA_PATH` to point to a different JSON file. See `data/cv.example.json` for the full schema.

## Rate Limiting

Per-IP, in-memory. `localhost` exempt.

| Endpoint    | Limit   |
| ----------- | ------- |
| `/`         | 30/min  |
| `/health`   | 60/min  |
| `/cv*`      | 30/min  |
| `/cv/pdf`   | 5/15min |

## Docker

```bash
just build && just run
```

## GCP Deploy

```bash
just gcloud-build
gcloud run deploy cv-rest-mcp-server --image gcr.io/$GCP_PROJECT/cv-rest-mcp-server --region us-central1 --platform managed --allow-unauthenticated
```

## Stack

FastAPI · FastMCP v3 · WeasyPrint · Jinja2 · Cloud Run-compatible (stateless, $PORT-aware)
