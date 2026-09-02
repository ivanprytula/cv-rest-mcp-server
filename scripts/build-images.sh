#!/usr/bin/env bash
# Manual image builder for first-time bootstrap, or when CI/CD is unavailable.
# Builds and pushes all three service images to Artifact Registry in parallel.
#
# Normal releases go through .github/workflows/deploy-app.yml — use this only
# to seed images before the first `terraform apply` (Cloud Run cannot start a
# service whose image does not exist yet), or to recover when Actions is down.
#
# Usage:
#   scripts/build-images.sh <gcp-project> [<gcp-region>]
#
# Example:
#   scripts/build-images.sh my-project europe-west1
#
# Images are tagged with BOTH the short git SHA (traceable, what CI deploys)
# and :latest (what terraform.tfvars references for a from-scratch apply).

set -euo pipefail

PROJECT="${1:?Set GCP project id as the first argument}"
REGION="${2:-europe-west1}"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/cv-images"
SHORT_SHA="$(git rev-parse --short=7 HEAD 2>/dev/null || echo manual)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERR:\033[0m %s\n' "$*" >&2; exit 1; }

# name -> Dockerfile. Keep in sync with deploy-app.yml's build_service calls.
SERVICES=(
    "api-core:Dockerfile"
    "api-games:services/games/Dockerfile"
    "spa-origin:frontend/Dockerfile"
)

log "Project: $PROJECT   Region: $REGION"
log "Repo:    $REPO"
log "Tags:    :$SHORT_SHA and :latest"

for entry in "${SERVICES[@]}"; do
    dockerfile="${entry#*:}"
    [[ -f "$dockerfile" ]] || die "missing Dockerfile: $dockerfile"
done

log "Ensuring Cloud Build API is enabled"
gcloud services enable cloudbuild.googleapis.com --project "$PROJECT" || true

# The Artifact Registry repo is created by Terraform (modules/iam_secrets).
# On a truly fresh project it will not exist yet, so create it here — this
# script exists precisely for the pre-`terraform apply` case.
if ! gcloud artifacts repositories describe cv-images \
    --location="$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    log "Creating Artifact Registry repo 'cv-images' (Terraform will adopt it)"
    gcloud artifacts repositories create cv-images \
        --project "$PROJECT" --location="$REGION" \
        --repository-format=docker \
        --description="Application images (api-core, api-games, spa-origin)"
fi

# Submit a build and print its id on stdout. Runs synchronously up to the
# submit call only; the build itself continues asynchronously.
#
# NOTE: the previous version backgrounded the redirect (`submit ... > f &`)
# and then read the file immediately, so the id was almost always empty and
# polling silently did nothing. Capture the id directly instead.
submit_build() {
    local name="$1" dockerfile="$2" cfg
    cfg="$(mktemp -t "cloudbuild-${name}-XXXXXX.yaml")"

    cat > "$cfg" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', '${dockerfile}',
           '-t', '${REPO}/${name}:${SHORT_SHA}',
           '-t', '${REPO}/${name}:latest', '.']
images:
  - '${REPO}/${name}:${SHORT_SHA}'
  - '${REPO}/${name}:latest'
EOF

    gcloud builds submit --project "$PROJECT" \
        --config "$cfg" --quiet --async --format='value(id)'
    rm -f "$cfg"
}

poll_build() {
    local build_id="$1" name="$2" build_status
    while :; do
        build_status="$(gcloud builds describe "$build_id" \
            --project "$PROJECT" --format='value(status)')"
        case "$build_status" in
            SUCCESS)
                log "$name build succeeded ($build_id)"
                return 0
                ;;
            FAILURE|INTERNAL_ERROR|TIMEOUT|CANCELLED|EXPIRED)
                warn "$name build $build_status — logs:"
                warn "  gcloud builds log $build_id --project $PROJECT"
                return 1
                ;;
            *)
                printf '  %-11s %s\n' "$name" "$build_status"
                sleep 5
                ;;
        esac
    done
}

declare -A BUILD_IDS
for entry in "${SERVICES[@]}"; do
    name="${entry%%:*}"
    dockerfile="${entry#*:}"
    log "Submitting $name ($dockerfile)"
    BUILD_IDS["$name"]="$(submit_build "$name" "$dockerfile")"
    log "  build id: ${BUILD_IDS[$name]}"
done

log "Waiting for builds to finish"
FAILED=0
for name in "${!BUILD_IDS[@]}"; do
    poll_build "${BUILD_IDS[$name]}" "$name" || FAILED=1
done

[[ "$FAILED" -eq 0 ]] || die "one or more builds failed"

log "All images pushed:"
for entry in "${SERVICES[@]}"; do
    log "  ${REPO}/${entry%%:*}:${SHORT_SHA}"
done

cat <<EOF

Next: deploy with Terraform (reads the :latest tags from terraform.tfvars)

  cd terraform && terraform plan && terraform apply

After the first apply, routine releases go through deploy-app.yml — Terraform
ignores drift on the image field (modules/cloud_run_service lifecycle).
EOF
