#!/usr/bin/env bash
# Cloud Run deploy automation for cv-rest-mcp-server.
#
# Mirrors .local/deploy-checklist.md step by step; every stage is idempotent.
#
# Usage:
#   scripts/deploy-cloud-run.sh <stage> [stage...]
#
# Stages:
#   bootstrap   enable APIs, runtime SA, CV bucket + IAM binding   (checklist 0-2)
#   upload-cv   publish data/cv.json to the bucket                 (checklist 2)
#   build       Cloud Build image                                  (checklist 3)
#   deploy      create/update Cloud Run service                    (checklist 4)
#   verify      health check + smoke URLs                          (checklist 5)
#   wif         one-time: GitHub OIDC federation for CD            (see checklist 7)
#   all         bootstrap build deploy verify                      (NOT upload-cv — run explicitly, personal data)
#
# Environment:
#   GCP_PROJECT  required — your EXISTING project id. This script never
#                creates projects (that is a billing/console decision).#   GCP_REGION   default europe-west1
#   SVC_NAME     default cv-rest-mcp-server
#   REPO         owner/name for `wif`; derived from git remote when unset.

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-}"   # required; validated per-stage by require_project
GCP_REGION="${GCP_REGION:-europe-west1}"
SVC_NAME="${SVC_NAME:-cv-rest-mcp-server}"
RUN_SA_ID="${SVC_NAME}-runtime"
DEPLOY_SA_ID="${SVC_NAME}-deployer"
CV_BUCKET="${GCP_PROJECT}-cv-data"

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

    # gcr.io tags are served by Artifact Registry: pushes land in a repo
    # literally named 'gcr.io' (multi-region us). Pre-create it so the build
    # SA only ever needs plain writer — no createOnPush permission.
    log "Ensuring Artifact Registry repo 'gcr.io' (legacy host backing)"
    if gcloud artifacts repositories describe gcr.io --location=us \
        --project "$GCP_PROJECT" >/dev/null 2>&1; then
        echo "exists, skipping"
    else
        gcloud artifacts repositories create gcr.io \
            --project "$GCP_PROJECT" --location=us \
            --repository-format=docker \
            --description="gcr.io legacy-host backing for $SVC_NAME images"
    fi
}

bootstrap() {
    require_project
    log "Enabling APIs on $GCP_PROJECT"
    gcloud services enable --project "$GCP_PROJECT" \
        cloudresourcemanager.googleapis.com run.googleapis.com \
        cloudbuild.googleapis.com storage.googleapis.com

    log "Runtime service account $RUN_SA_ID"
    if gcloud iam service-accounts describe "${RUN_SA_ID}@${GCP_PROJECT}.iam.gserviceaccount.com" \
        --project "$GCP_PROJECT" >/dev/null 2>&1; then
        echo "exists, skipping"
    else
        gcloud iam service-accounts create "$RUN_SA_ID" \
            --project "$GCP_PROJECT" \
            --display-name="$SVC_NAME Cloud Run runtime" \
            --description="Reads CV content from GCS; no other permissions by design"
    fi

    log "CV bucket gs://$CV_BUCKET"
    if gcloud storage buckets describe "gs://$CV_BUCKET" >/dev/null 2>&1; then
        echo "exists, skipping create"
    else
        gcloud storage buckets create "gs://$CV_BUCKET" \
            --location="$GCP_REGION" --uniform-bucket-level-access
    fi
    # object versioning = free history/rollback for cv.json (idempotent)
    gcloud storage buckets update "gs://$CV_BUCKET" --versioning

    log "Grant runtime SA read on its bucket only"
    gcloud storage buckets add-iam-policy-binding "gs://$CV_BUCKET" \
        --member="serviceAccount:${RUN_SA_ID}@${GCP_PROJECT}.iam.gserviceaccount.com" \
        --role=roles/storage.objectViewer --condition=None >/dev/null

    ensure_build_permissions
    warn "No keys created anywhere: Cloud Run injects short-lived credentials automatically."
}

upload_cv() {
    require_project
    [ -f data/cv.json ] || die "data/cv.json not found"
    log "Publishing data/cv.json to gs://$CV_BUCKET/cv.json"
    gcloud storage cp data/cv.json "gs://$CV_BUCKET/cv.json"
    echo "Live within ~30s (CV_REFRESH_SECONDS). Rollback: gcloud storage ls -a \"gs://$CV_BUCKET/cv.json\""
}

build() {
    local build_id build_status
    require_project
    log "Cloud Build: gcr.io/$GCP_PROJECT/$SVC_NAME"
    build_id="$(gcloud builds submit --project "$GCP_PROJECT" \
        --tag "gcr.io/${GCP_PROJECT}/${SVC_NAME}" \
        --quiet --async --format='value(id)')"
    log "Cloud Build started: $build_id"

    while :; do
        build_status="$(gcloud builds describe "$build_id" \
            --project "$GCP_PROJECT" --format='value(status)')"
        case "$build_status" in
            SUCCESS)
                log "Cloud Build succeeded: $build_id"
                return 0
                ;;
            FAILURE|INTERNAL_ERROR|TIMEOUT|CANCELLED|EXPIRED)
                die "Cloud Build failed with status $build_status: $build_id"
                ;;
            *)
                printf 'waiting for build (%s)...\n' "${build_status:-UNKNOWN}"
                sleep 5
                ;;
        esac
    done
}

deploy() {
    require_project
    log "Deploying $SVC_NAME to $GCP_REGION"
    # --set-env-vars REPLACES all vars every time: this line is the single
    # source of truth for runtime config. Contact_* come from .env via
    # just's dotenv-load (empty = omitted from Swagger UI).
    gcloud run deploy "$SVC_NAME" \
        --project "$GCP_PROJECT" --region "$GCP_REGION" --quiet \
        --image "gcr.io/${GCP_PROJECT}/${SVC_NAME}" \
        --service-account "${RUN_SA_ID}@${GCP_PROJECT}.iam.gserviceaccount.com" \
        --allow-unauthenticated \
        --cpu 1 --memory 512Mi \
        --max-instances 1 \
        --set-env-vars "TRUST_PROXY=true,CLIENT_IP_XFF_ENTRY=2,BLOCKED_IPS_FILE=config/blocked_geo.txt,FAILBAN_THRESHOLD=6,CV_DATA_GCS_URI=gs://${CV_BUCKET}/cv.json,CV_REFRESH_SECONDS=30,CONTACT_NAME=${CONTACT_NAME:-},CONTACT_EMAIL=${CONTACT_EMAIL:-}"
}

verify() {
    require_project
    local url health attempt
    url="$(gcloud run services describe "$SVC_NAME" \
        --project "$GCP_PROJECT" --region "$GCP_REGION" --format 'value(status.url)')"
    log "Service URL: $url"

    health=""
    for attempt in $(seq 1 12); do
        if health="$(curl -fsS --max-time 10 "$url/health" 2>/dev/null)"; then break; fi
        echo "waiting for revision ($attempt/12)..."
        sleep 5
    done
    [ -n "$health" ] || die "/health never returned OK — check logs: gcloud run services logs read $SVC_NAME --region $GCP_REGION"
    echo "$health"

    case "$health" in
        *'"cv_source":"gcs"'*) ;;
        *placeholder*)
            warn "cv_source is placeholder — upload content: scripts/deploy-cloud-run.sh upload-cv" ;;
    esac

    log "Smoke: $url/ · $url/cv/html?theme=original · $url/cv/pdf?theme=modern (rate-limited)"
}

wif() {
    require_project
    local pool="github" provider="gh-actions"
    REPO="${REPO:-$(git remote get-url origin | sed -E 's#.*[:/]([^/]+/[^/.]+)(\.git)?$#\1#')}"
    [ -n "$REPO" ] || die "Cannot derive repo from git remote; set REPO=owner/name"

    log "WIR pool/provider for $REPO"
    gcloud iam workload-identity-pools describe "$pool" --location global --project "$GCP_PROJECT" >/dev/null 2>&1 ||
        gcloud iam workload-identity-pools create "$pool" --location global --project "$GCP_PROJECT" \
            --display-name="GitHub Actions"

    gcloud iam workload-identity-pools providers describe "$provider" \
        --workload-identity-pool "$pool" --location global --project "$GCP_PROJECT" >/dev/null 2>&1 ||
        gcloud iam workload-identity-pools providers create-oidc "$provider" \
            --workload-identity-pool "$pool" --location global --project "$GCP_PROJECT" \
            --issuer-uri="https://token.actions.githubusercontent.com" \
            --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
            --attribute-condition="assertion.repository==\"$REPO\""

    log "Deployer SA $DEPLOY_SA_ID + least-privilege roles"
    if gcloud iam service-accounts describe "${DEPLOY_SA_ID}@${GCP_PROJECT}.iam.gserviceaccount.com" \
        --project "$GCP_PROJECT" >/dev/null 2>&1; then
        echo "exists, skipping create"
    else
        gcloud iam service-accounts create "$DEPLOY_SA_ID" \
            --project "$GCP_PROJECT" \
            --display-name="$SVC_NAME GitHub Actions deployer"
    fi
    local deploy_sa="${DEPLOY_SA_ID}@${GCP_PROJECT}.iam.gserviceaccount.com"
    local pool_full github_principal
    pool_full="$(gcloud iam workload-identity-pools describe "$pool" --location global \
        --project "$GCP_PROJECT" --format 'value(name)')"
    github_principal="principalSet://iam.googleapis.com/${pool_full}/attribute.repository/${REPO}"
    # Allow this repository's GitHub OIDC principal to impersonate only the deployer SA.
    gcloud iam service-accounts add-iam-policy-binding "$deploy_sa" \
        --project "$GCP_PROJECT" --member="$github_principal" \
        --role=roles/iam.workloadIdentityUser --condition=None >/dev/null
    gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
        --member="serviceAccount:$deploy_sa" --role=roles/run.admin --condition=None >/dev/null
    # require_project validates access via `gcloud projects describe`, which
    # needs projects.get — browser is the least-privilege role for that
    # (projectViewer is often not grantable under org policy).
    gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
        --member="serviceAccount:$deploy_sa" --role=roles/browser --condition=None >/dev/null
    gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
        --member="serviceAccount:$deploy_sa" --role=roles/cloudbuild.builds.builder --condition=None >/dev/null
    # gcloud builds submit runs as the project's default Cloud Build SA; the
    # deployer must be allowed to act as that SA, scoped to this account only.
    local build_sa
    build_sa="$(gcloud builds get-default-service-account --project "$GCP_PROJECT")"
    gcloud iam service-accounts add-iam-policy-binding "$build_sa" \
        --project "$GCP_PROJECT" --member="serviceAccount:$deploy_sa" \
        --role=roles/iam.serviceAccountUser --condition=None >/dev/null
    # impersonate the runtime SA during deploys (scoped to that SA only)
    gcloud iam service-accounts add-iam-policy-binding "${RUN_SA_ID}@${GCP_PROJECT}.iam.gserviceaccount.com" \
        --project "$GCP_PROJECT" --member="serviceAccount:$deploy_sa" \
        --role=roles/iam.serviceAccountUser --condition=None >/dev/null

    cat <<EOF

Wire these repository secrets/vars (needs repo admin):
  gh secret set GCP_WIF_PROVIDER --body "$pool_full/providers/$provider"
  gh secret set GCP_DEPLOY_SA    --body "$deploy_sa"
  gh variable set GCP_PROJECT    --body "$GCP_PROJECT"
  gh variable set GCP_REGION     --body "$GCP_REGION"
  gh variable set SVC_NAME       --body "$SVC_NAME"

Then trigger: Actions → Deploy → Run workflow.
EOF
}

case "${1:-}" in
    # require_project) require_project ;;
    bootstrap) shift; bootstrap ;;
    upload-cv) shift; upload_cv ;;
    build)     shift; build ;;
    deploy)    shift; deploy ;;
    verify)    shift; verify ;;
    wif)       shift; wif ;;
    all)       shift; bootstrap; build; deploy; verify ;;
    *) sed -n '2,25p' "$0"; exit 1 ;;
esac
