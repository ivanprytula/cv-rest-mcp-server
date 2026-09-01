@help:
    just --list

setup:
    uv venv
    uv sync --group dev

dev-local:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload --reload-include '*.html'

dev-spa:
    cd frontend && npm run dev -- --port 5173

code-quality:
    uv run ruff check .
    uv run ruff format .
    uv run ty check

test:
    uv run pytest

# Browser e2e tests (Playwright); excluded from `just test` by default.
test-ui:
    uv run playwright install chromium
    uv run pytest -m e2e --no-cov

# Recompute the SHA-256 hash of FastAPI's /docs inline init script.
# Run after upgrading FastAPI; paste output into app/main.py _CSP_DIRECTIVE.
# Requires dev server running on :8080 (just dev).
csp-swaggerui-hash:
    python3 scripts/csp_swaggerui_hash.py

test-pdf:
    curl localhost:8080/cv/pdf?theme=modern -o /tmp/test.pdf

css:
    npm run css

# Build all three service images (api-core, spa-origin, api-games) and push to GCR.
# Use this for initial bootstrap or when CI/CD is unavailable.
# Usage: just build-images <gcp-project> [<gcp-region>]
build-images PROJECT REGION="europe-west1":
    scripts/build-images.sh {{ PROJECT }} {{ REGION }}

# Refresh config/blocked_geo.txt from ipdeny aggregated country zones
update-geo-blocklist:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    countries="ru ir kp by cu sy ve mm"
    for c in $countries; do
        curl -sf "https://www.ipdeny.com/ipblocks/data/aggregated/${c}-aggregated.zone" \
            -o "${tmp}/${c}-v4.zone"
    done
    curl -sf "https://www.ipdeny.com/ipv6/ipaddresses/blocks/ipv6-all-zones.tar.gz" \
        -o "$tmp/v6.tar.gz"
    mkdir "$tmp/v6"
    tar xzf "$tmp/v6.tar.gz" -C "$tmp/v6"
    for c in $countries; do
        [ -f "$tmp/v6/${c}.zone" ] && cp "$tmp/v6/${c}.zone" "$tmp/${c}-v6.zone" || true
    done
    out="config/blocked_geo.txt"
    {
        echo "# Geo blocklist — generated file, do not edit by hand."
        echo "# Refresh: just update-geo-blocklist"
        echo "# Source: https://www.ipdeny.com (aggregated IPv4+IPv6 country zones)"
        echo "# Countries: $(echo $countries | tr 'a-z' 'A-Z') · Generated: $(date -u +%Y-%m-%d)"
        cat "$tmp"/*.zone | sort -u
    } > "$out"
    echo "Wrote $out ($(grep -vc '^#' "$out") networks)"

# ── Phase 1a edge IaC (single managed environment; terraform/ dir) ──────────
# Remote state + locking: just deploy bootstrap-state (once)
tf:
    cd terraform && terraform init

tf-plan:
    cd terraform && terraform plan -out=tfplan

tf-apply:
    cd terraform && terraform apply "tfplan"

# Generate architecture diagram from terraform graph + graphviz
tf-graph:
    cd terraform && terraform graph -type=plan | dot -Tpng > ../docs/graph.png

# ── Local multi-service dev (Docker Compose) ─────────────────────────────────

up:
    docker compose up -d --build --remove-orphans

down:
    docker compose down

logs:
    docker compose logs --follow

tf-fmt:
    cd terraform && terraform fmt -recursive && terraform validate

tf-lint:
    cd terraform && tflint --config .tflint.hcl

# ── Phased apply (learn TF incrementally) ─────────────────────────────────────
# Run `just tf` (init) once before using these.
# Phase 1: static bucket — fully standalone, no dependencies
# Example: just tf-apply1
tf-apply1:
    cd terraform && terraform apply -target=module.static_bucket

# Phase 2: Cloud Run services — needs Docker image built + pushed first
# Example: just tf-apply2
tf-apply2:
    cd terraform && terraform apply -target=module.run

# Phase 3: HTTPS load balancer + Cloud CDN — needs NEGs from phase 2
# Example: just tf-apply3
tf-apply3:
    cd terraform && terraform apply -target=module.edge_lb

# Phase 4: DNS records — needs LB IP from phase 3
# Example: just tf-apply4
tf-apply4:
    cd terraform && terraform apply -target=module.dns

# Apply all remaining resources (catch-all, after phased steps)
tf-apply-rest:
    cd terraform && terraform apply

tf-sec:
    cd terraform && uvx --from 'checkov' checkov -d . --quiet --compact --skip-check CKV_GCP_62,CKV_GCP_114,CKV_GCP_28
    uv run python scripts/ensure_deny_public.py terraform --cdn-origin-resource terraform/modules/static_bucket/main.tf:google_storage_bucket.bucket

# Path-scoped deny-public guard alone (no checkov). CDN origin is the sole exception.
tf-deny-public:
    uv run python scripts/ensure_deny_public.py terraform --cdn-origin-resource terraform/modules/static_bucket/main.tf:google_storage_bucket.bucket

# Invalidate the Cloud CDN cache for a path prefix after changing a file in place.
tf-cdn-invalidate path='/assets/':
    gcloud compute url-maps invalidate-cdn-cache cv-edge-url-map --path '{{path}}'

build:
    docker buildx build -t cv-rest-mcp-server .

run:
    docker run -p 8080:8080 cv-rest-mcp-server

# One-time operator setup:
#   just deploy bootstrap
#   just deploy upload-cv
#   just deploy wif
# Single cloud entry point — every GCP op runs via scripts/deploy-cloud-run.sh
@deploy *args:
    ./scripts/deploy-cloud-run.sh {{args}}

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
