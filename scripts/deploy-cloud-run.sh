#!/usr/bin/env bash
# Cloud Run operational setup — one-time bootstrap and data management.
#
# EXECUTION ORDER (required):
#   1. bootstrap          Enable cloudresourcemanager API, create CV bucket, grant Cloud Build permissions
#   2. bootstrap-state    Create versioned TF remote-state bucket + init
#   3. bootstrap-secrets  Create Secret Manager secrets (cv-jwt-signing-key, refresh-token-pepper)
#   4. (Run: terraform apply)  Terraform deploys IAM, Org Policies, Cloud Run services
#   5. upload-cv          Publish data/cv.json to GCS (application data)
#   6. verify             Health check + smoke test URLs (optional, manual verification)
#
# Usage:
#   scripts/deploy-cloud-run.sh <stage>
#
# Environment:
#   GCP_PROJECT  required — your EXISTING project id. This script never
#                creates projects (that is a billing/console decision).
#   GCP_ENV      default production (e.g. dev, stage, production)
#   GCP_REGION   default europe-west1
#
# Note: GitHub WIF (Workload Identity Federation) setup is now in Terraform
# (terraform/modules/github_wif/). Set setup_github_wif=true in terraform.tfvars.

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-}"   # required; validated per-stage by require_project
GCP_ENV="${GCP_ENV:-dev}"
GCP_REGION="${GCP_REGION:-europe-west1}"
CV_BUCKET="${GCP_PROJECT}-cv-data"
# Terraform remote state (Phase 1a). The SAME versioned bucket provides both
# state storage and lock coordination — the GCS backend locks via an object
# write-hold in this bucket, so there is no separate "lock bucket" to create.
TF_STATE_BUCKET="${TF_STATE_BUCKET:-${GCP_PROJECT}-${GCP_ENV}-tfstate}"
TF_STATE_PREFIX="${TF_STATE_PREFIX:-terraform/state}"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERR:\033[0m %s\n' "$*" >&2; exit 1; }

require_project() {
    : "${GCP_PROJECT:?Set GCP_PROJECT to your EXISTING project id (this script does not create projects)}"
    local project_error
    if project_error="$(gcloud projects describe "$GCP_PROJECT" 2>&1 >/dev/null)"; then
        return 0
    fi
    case "$project_error" in
        *"NOT_FOUND"*|*"not found"*)
            die "Project '$GCP_PROJECT' does not exist. Set GCP_PROJECT to the existing Google Cloud project ID."
            ;;
        *"PERMISSION_DENIED"*|*"permission"*|*"Permission"*)
            die "The authenticated identity cannot access project '$GCP_PROJECT'. Check the GitHub WIF service account and its project IAM roles."
            ;;
        *)
            die "Could not access project '$GCP_PROJECT': ${project_error:-unknown gcloud error}"
            ;;
    esac
}

ensure_build_permissions() {
    # Cloud Build resolves the uploaded source (and pushes the image) as its
    # configured build SA. Hardened projects strip the automatic Editor grant
    # from the default compute SA, so builds die with "storage.objects.get
    # denied on <project>_cloudbuild". Grant the minimum, idempotently.
    local pnum build_sa role
    pnum="$(gcloud projects describe "$GCP_PROJECT" --format 'value(projectNumber)')"
    build_sa="${pnum}-compute@developer.gserviceaccount.com"
    log "Ensuring build SA has build permissions ($build_sa)"
    for role in roles/storage.objectAdmin roles/artifactregistry.writer roles/logging.logWriter; do
        gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
            --member="serviceAccount:$build_sa" --role="$role" --condition=None >/dev/null
    done

    # The app image repo itself (cv-images, regional Artifact Registry) is
    # provisioned by Terraform (modules/iam_secrets) — not here. This grants
    # only the project-level roles Cloud Build needs to write to it.
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: One-time bootstrap — cloudresourcemanager API, CV bucket, Cloud Build IAM
# ─────────────────────────────────────────────────────────────────────────────
bootstrap() {
    require_project
    log "STEP 1: Bootstrap APIs and CV bucket"

    log "  1a. Enabling cloudresourcemanager API on $GCP_PROJECT"
    # Only this one is needed here: Terraform's own google_project_service
    # resources (which enable run/cloudbuild/storage/compute/dns/secretmanager/
    # artifactregistry — see terraform/modules/gcp_apis) require
    # cloudresourcemanager already active to apply at all on a fresh project.
    gcloud services enable --project "$GCP_PROJECT" \
        cloudresourcemanager.googleapis.com

    # Runtime service accounts (api-core-runtime, spa-origin-runtime,
    # api-games-runtime) are created by Terraform (modules/iam_secrets),
    # which also grants api-core-runtime read access to the CV bucket below.

    log "  1b. CV bucket gs://$CV_BUCKET (application data storage)"
    if gcloud storage buckets describe "gs://$CV_BUCKET" >/dev/null 2>&1; then
        echo "    exists, skipping create"
    else
        gcloud storage buckets create "gs://$CV_BUCKET" \
            --location="$GCP_REGION" --uniform-bucket-level-access
    fi
    # object versioning = free history/rollback for cv.json (idempotent)
    gcloud storage buckets update "gs://$CV_BUCKET" --versioning

    ensure_build_permissions

    cat <<EOF

✓ STEP 1 complete. Next: STEP 2

EOF
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Terraform remote state — versioned bucket + backend init
# ─────────────────────────────────────────────────────────────────────────────
bootstrap_state() {
    require_project
    log "STEP 2: Terraform remote state bucket + backend init"

    log "  2a. Remote-state bucket gs://$TF_STATE_BUCKET (versioned = locking + history)"
    if gcloud storage buckets describe "gs://$TF_STATE_BUCKET" >/dev/null 2>&1; then
        echo "    exists, skipping create"
    else
        gcloud storage buckets create "gs://$TF_STATE_BUCKET" \
            --location="$GCP_REGION" --default-storage-class=STANDARD \
            --public-access-prevention
    fi
    # Object versioning is the GCS locking + rollback mechanism (idempotent).
    gcloud storage buckets update "gs://$TF_STATE_BUCKET" --versioning

    log "  2b. Configuring Terraform backend (gcs, prefix=$TF_STATE_PREFIX)"
    (
        cd terraform
        terraform init -force-copy \
            -backend-config="bucket=$TF_STATE_BUCKET" \
            -backend-config="prefix=$TF_STATE_PREFIX"
    )

    cat <<EOF

✓ STEP 2 complete. Next: STEP 3

EOF
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Secret Manager secrets — JWT key + refresh token pepper
# ─────────────────────────────────────────────────────────────────────────────
bootstrap_secrets() {
    require_project
    log "STEP 3: Create Secret Manager secrets"

    log "  3a. Creating Secret Manager secrets"
    for secret in cv-jwt-signing-key cv-refresh-token-pepper; do
        if gcloud secrets describe "$secret" --project "$GCP_PROJECT" >/dev/null 2>&1; then
            echo "    $secret exists, skipping create"
        else
            gcloud secrets create "$secret" --project "$GCP_PROJECT" --replication-policy="automatic"
            echo "    Created $secret. Add initial version with: gcloud secrets versions add $secret --data-file=-"
        fi
    done

    log "  3b. IAM: runtime SA gets secret read access (terraform handles this via iam_secrets module)"
    warn "Secret creation/versions are managed here only. terraform/modules/iam_secrets/ only binds IAM access. For manual updates, use: gcloud secrets versions add <secret-id> --data-file=-"

    cat <<EOF

✓ STEP 3 complete. Next: STEP 4 (manual, not in this script)

EOF
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Terraform apply (MANUAL — not in this script)
# ─────────────────────────────────────────────────────────────────────────────
# Run this manually in the terraform/ directory:
#   cd terraform
#   # Edit terraform/terraform.tfvars with your values
#   terraform plan
#   terraform apply
# This deploys: IAM, Org Policies, GitHub WIF, Cloud Run services, DNS, LB, etc.
#
# After terraform apply succeeds, continue to STEP 5.

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Upload CV data — publish cv.json to GCS
# ─────────────────────────────────────────────────────────────────────────────
upload_cv() {
    require_project
    log "STEP 5: Upload CV data (after terraform apply)"

    [ -f data/cv.json ] || die "data/cv.json not found"
    log "  Publishing data/cv.json to gs://$CV_BUCKET/cv.json"
    gcloud storage cp data/cv.json "gs://$CV_BUCKET/cv.json"
    echo "  Live within ~30s (CV_REFRESH_SECONDS). Rollback: gcloud storage ls -a \"gs://$CV_BUCKET/cv.json\""
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: Verification — health check + smoke tests (optional, manual)
# ─────────────────────────────────────────────────────────────────────────────
verify() {
    require_project
    log "STEP 6: Verify Cloud Run deployments (optional, manual)"

    local svc url health attempt api_core_url
    for svc in api-core api-games spa-origin; do
        log "  === $svc ==="
        url="$(gcloud run services describe "$svc" \
            --project "$GCP_PROJECT" --region "$GCP_REGION" --format 'value(status.url)')"
        echo "    Service URL: $url"
        [ "$svc" = "api-core" ] && api_core_url="$url"

        health=""
        for attempt in $(seq 1 12); do
            if health="$(curl -fsS --max-time 10 "$url/health" 2>/dev/null)"; then break; fi
            echo "    waiting for revision ($attempt/12)..."
            sleep 5
        done
        [ -n "$health" ] || die "$svc /health never returned OK — check logs: gcloud run services logs read $svc --region $GCP_REGION"
        echo "    Health check: OK"
        echo "    Response: $health"
    done

    case "$health" in
        *'"cv_source":"gcs"'*) ;;
        *placeholder*)
            warn "cv_source is placeholder — upload content: scripts/deploy-cloud-run.sh upload-cv" ;;
    esac

    log "  Smoke tests (api-core):"
    echo "    $api_core_url/"
    echo "    $api_core_url/cv/html?theme=original"
    echo "    $api_core_url/cv/pdf?theme=modern (rate-limited)"
}

if [[ "$#" -ne 1 ]]; then
    sed -n '2,30p' "$0"
    exit 1
fi

case "$1" in
    bootstrap)        bootstrap ;;
    bootstrap-state)  bootstrap_state ;;
    bootstrap-secrets) bootstrap_secrets ;;
    upload-cv)        upload_cv ;;
    verify)           verify ;;
    *)                sed -n '2,30p' "$0"; exit 1 ;;
esac
