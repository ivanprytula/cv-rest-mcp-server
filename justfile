help:
    @echo "Available recipes:"
    @echo "  setup         - Create venv and install dependencies"
    @echo "  dev           - Run dev server with hot reload"
    @echo "  lint          - Run ruff linter"
    @echo "  format        - Run ruff formatter"
    @echo "  typecheck     - Run ty type checker"
    @echo "  test          - Run pytest"
    @echo "  test-pdf      - Test PDF generation endpoint"
    @echo "  mcp-init      - Initialize MCP session (prints session ID)"
    @echo "  mcp-tool      - Call MCP tool (usage: just mcp-tool <name> '<args>')"
    @echo "  mcp-call      - Init + call tool in one shot (usage: just mcp-call <name> '<args>')"
    @echo "  build         - Build Docker image"
    @echo "  run           - Run Docker container"
    @echo "  gcloud-build  - Build and push to GCR"
    @echo "  help          - Show this help message"

setup:
    uv venv
    uv sync --extra dev

lint:
    uv run ruff check .

format:
    uv run ruff format .

typecheck:
    uv run ty check

build:
    docker buildx build -t cv-mcp-agent .

run:
    docker run -p 8080:8080 cv-mcp-agent

dev:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

test:
    uv run pytest

test-pdf:
    curl localhost:8080/cv/pdf?theme=modern -o /tmp/test.pdf

gcloud-build:
    gcloud builds submit --tag gcr.io/$$GCP_PROJECT/cv-mcp-agent

mcp-init:
    curl -s -D - -X POST http://localhost:8080/mcp/ \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

mcp-tool SESSION_ID TOOL_NAME ARGUMENTS:
    curl -s -X POST http://localhost:8080/mcp/ \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "MCP-Session-Id: {{SESSION_ID}}" \
        -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"{{TOOL_NAME}}","arguments":{{ARGUMENTS}}}}'

# just mcp-call get_cv '{}'
# just mcp-call generate_cv_pdf '{"theme":"classic"}'
mcp-call TOOL_NAME ARGUMENTS:
    @export MCP_SESSION_ID=$$(curl -s -D - -X POST http://localhost:8080/mcp/ \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"just","version":"1.0"}}}' \
        | grep -i 'mcp-session-id' | tr -d '\r' | awk '{print $$2}') && \
    curl -s -X POST http://localhost:8080/mcp/ \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "MCP-Session-Id: $$MCP_SESSION_ID" \
        -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"{{TOOL_NAME}}","arguments":{{ARGUMENTS}}}}'
