@help:
    just --list

setup:
    uv venv
    uv sync --extra dev

dev:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload --reload-include '*.html'

code-quality:
    uv run ruff check .
    uv run ruff format .
    uv run ty check

test:
    uv run pytest

test-pdf:
    curl localhost:8080/cv/pdf?theme=modern -o /tmp/test.pdf

build:
    docker buildx build -t cv-mcp-agent .

run:
    docker run -p 8080:8080 cv-mcp-agent

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
