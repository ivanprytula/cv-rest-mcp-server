#!/usr/bin/env bash
# Manual image builder for initial deployment (before tf apply).
# Builds and pushes all three service images to GCR in parallel.
# Use this for first-time bootstrap or when CI/CD is unavailable.
#
# Usage:
#   scripts/build-images.sh <gcp-project> [<gcp-region>]
#
# Example:
#   scripts/build-images.sh my-project europe-west1

set -euo pipefail

PROJECT="${1:?Set GCP_PROJECT as first argument}"
REGION="${2:-europe-west1}"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERR:\033[0m %s\n' "$*" >&2; exit 1; }

log "Building images for project: $PROJECT (region: $REGION)"

# Ensure Cloud Build API is enabled
log "Enabling Cloud Build API..."
gcloud services enable cloudbuild.googleapis.com --project "$PROJECT" || true

# Build api-core (from root Dockerfile)
log "Building api-core image..."
gcloud builds submit --project "$PROJECT" \
  --tag "gcr.io/${PROJECT}/api-core:latest" \
  --file Dockerfile \
  --async --format='value(id)' > /tmp/api_build_id.txt &
API_BUILD_ID=$(cat /tmp/api_build_id.txt)

# Build spa-origin (from Dockerfile.spa)
log "Building spa-origin image..."
gcloud builds submit --project "$PROJECT" \
  --tag "gcr.io/${PROJECT}/spa-origin:latest" \
  --file Dockerfile.spa \
  --async --format='value(id)' > /tmp/spa_build_id.txt &
SPA_BUILD_ID=$(cat /tmp/spa_build_id.txt)

# Build api-games (from services/games/Dockerfile)
log "Building api-games image..."
gcloud builds submit --project "$PROJECT" \
  --tag "gcr.io/${PROJECT}/api-games:latest" \
  --file services/games/Dockerfile \
  --async --format='value(id)' > /tmp/games_build_id.txt &
GAMES_BUILD_ID=$(cat /tmp/games_build_id.txt)

wait

# Poll for all builds to complete
poll_build() {
  local build_id=$1
  local name=$2
  while :; do
    STATUS=$(gcloud builds describe "$build_id" --project "$PROJECT" --format='value(status)')
    case "$STATUS" in
      SUCCESS)
        log "$name build succeeded: $build_id"
        return 0
        ;;
      FAILURE|INTERNAL_ERROR|TIMEOUT|CANCELLED|EXPIRED)
        die "$name build failed with status $STATUS: $build_id"
        ;;
      *)
        printf '  %s build status: %s (waiting...)\n' "$name" "$STATUS"
        sleep 5
        ;;
    esac
  done
}

log "Polling for build completion..."
poll_build "$API_BUILD_ID" "api-core" &
poll_build "$SPA_BUILD_ID" "spa-origin" &
poll_build "$GAMES_BUILD_ID" "api-games" &
wait

log "All images built successfully:"
log "  gcr.io/${PROJECT}/api-core:latest"
log "  gcr.io/${PROJECT}/spa-origin:latest"
log "  gcr.io/${PROJECT}/api-games:latest"
log ""
log "Next: Run terraform apply to deploy services to Cloud Run:"
log "  cd terraform && terraform apply"
