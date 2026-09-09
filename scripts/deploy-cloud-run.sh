#!/usr/bin/env bash
# Cloud Run operational setup — one-time bootstrap and data management.
#
# EXECUTION ORDER (required):
#   1. bootstrap          Enable cloudresourcemanager API, create CV bucket, grant Cloud Build permissions
#   2. bootstrap-state    Create versioned TF remote-state bucket + init
#   3. bootstrap-secrets  Create empty Secret Manager secrets (you add the values)
#   4. (Run: terraform apply)  Terraform deploys IAM, Org Policies, Cloud Run services,
#                          Cloud SQL (Phase 2, enable_cloud_sql=true)
#   5. bootstrap-database-url  Compose+store cv-database-url (app role) and
#                          cv-migration-database-url (superuser) from the Cloud
#                          SQL connection name (needs step 4's instance to
#                          exist; re-run terraform apply once to pick up the
#                          secrets). Requires POSTGRES_PASSWORD to be set.
#   5b. bootstrap-app-role Strip BYPASSRLS/SUPERUSER from cv_app so row-level
#                          security actually applies to it (Cloud SQL grants
#                          it by default via cloudsqlsuperuser membership).
#   6. upload-cv           Publish data/cv.json to GCS (application data)
#   7. verify              Health check + smoke test URLs (optional, manual verification)
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
GCP_ENV="${GCP_ENV:-production}"  # default production (e.g. dev, stage, production)
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
# STEP 3: Secret Manager secrets — JWT key, refresh pepper, first-admin password
# ─────────────────────────────────────────────────────────────────────────────

bootstrap_secrets() {
    require_project
    log "STEP 3: Create Secret Manager secrets (empty containers)"

    log "  3a. Creating secrets"
    for secret in cv-jwt-signing-key cv-refresh-token-pepper cv-first-admin-password cv-db-password cv-database-url cv-migration-database-url cv-anthropic-api-key; do
        if gcloud secrets describe "$secret" --project "$GCP_PROJECT" >/dev/null 2>&1; then
            echo "    $secret exists, skipping create"
        else
            gcloud secrets create "$secret" --project "$GCP_PROJECT" --replication-policy="automatic"
            echo "    Created $secret (no version yet)"
        fi
    done

    log "  3b. IAM: runtime SA read access is granted by terraform (modules/iam_secrets) —
       add each new secret id to api_core_secret_ids in terraform.tfvars"
    warn "Secret values are NEVER set by this script. Add them yourself below."

    cat <<EOF

  ── Add a version to each secret (paste your own value, then Ctrl-D) ──

    gcloud secrets versions add cv-jwt-signing-key \\
      --project $GCP_PROJECT --data-file=-

    gcloud secrets versions add cv-refresh-token-pepper \\
      --project $GCP_PROJECT --data-file=-

    gcloud secrets versions add cv-first-admin-password \\
      --project $GCP_PROJECT --data-file=-

    gcloud secrets versions add cv-db-password \\
      --project $GCP_PROJECT --data-file=-

    gcloud secrets versions add cv-anthropic-api-key \\
      --project $GCP_PROJECT --data-file=-
  (optional — leave the secret with no version if CV-intake extraction is
   not enabled yet; api-core boots fine either way)

  cv-database-url and cv-migration-database-url are NOT filled in here —
  they're composed from cv-db-password / POSTGRES_PASSWORD + the Cloud SQL
  connection name (only known after terraform apply creates the instance).
  Run scripts/deploy-cloud-run.sh bootstrap-database-url once step 4
  (terraform apply) has created the instance.

  Or generate a strong random value without it touching your shell history:

    python3 -c "import secrets;print(secrets.token_urlsafe(32))" \\
      | tr -d '\\n' \\
      | gcloud secrets versions add <secret-id> --project $GCP_PROJECT --data-file=-

  Read a value back (e.g. the admin password, to log in the first time):

    gcloud secrets versions access latest --secret=cv-first-admin-password \\
      --project $GCP_PROJECT

  WARNING: a secret with NO version breaks silently rather than loudly —
  app/auth/crypto.py HMACs with an empty pepper, and
  seed_first_admin_from_settings() skips seeding when the password is empty,
  so login is impossible while everything *looks* configured.

EOF

    cat <<EOF

✓ STEP 3 complete. Next: STEP 4 (manual, not in this script)

EOF
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Compose + store cv-database-url (Phase 2 Cloud SQL, after terraform
# apply has created the instance)
# ─────────────────────────────────────────────────────────────────────────────
bootstrap_database_url() {
    require_project
    log "STEP 5: Compose Cloud SQL DB URLs and set the postgres superuser password"

    # database_name/database_user match modules/cloud_sql/variables.tf defaults
    # (cv_portfolio/cv_app) — update both places together if either changes.
    local database_name="cv_portfolio"
    local database_user="cv_app"
    local instance_name="${CLOUDSQL_INSTANCE:-cv-postgres}"
    local postgres_password="${POSTGRES_PASSWORD:-}"

    if [[ -z "$postgres_password" ]]; then
        die "Set POSTGRES_PASSWORD to your Cloud SQL postgres superuser password before running bootstrap-database-url. Example: export POSTGRES_PASSWORD=<your-postgres-superuser-password>"
    fi
    # Composed into a connection URL below without percent-encoding, and
    # bootstrap-app-role parses it back out the same way — so it cannot
    # contain any of the URL's own delimiter characters.
    if [[ "$postgres_password" == *[@#/?]* ]]; then
        die "POSTGRES_PASSWORD must not contain '@', '#', '/', or '?' — these are not percent-encoded when composing the connection URL."
    fi

    local connection_name
    connection_name="$(gcloud sql instances describe "$instance_name" \
        --project "$GCP_PROJECT" --format 'value(connectionName)')" \
        || die "Cloud SQL instance '$instance_name' not found — run terraform apply first (STEP 4)."

    log "  Setting the Cloud SQL postgres password for instance $instance_name"
    gcloud sql users set-password postgres \
        --project "$GCP_PROJECT" \
        --instance "$instance_name" \
        --password "$postgres_password" >/dev/null

    local app_password
    app_password="$(gcloud secrets versions access latest --secret=cv-db-password --project "$GCP_PROJECT")" \
        || die "cv-db-password has no version yet — run: gcloud secrets versions add cv-db-password --project $GCP_PROJECT --data-file=-"

    log "  Composing DATABASE_URL (asyncpg, Auth Proxy Unix-socket path)"
    printf 'postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s' \
        "$database_user" "$app_password" "$database_name" "$connection_name" \
        | gcloud secrets versions add cv-database-url --project "$GCP_PROJECT" --data-file=-

    log "  Composing cv-migration-database-url (superuser, same database, same Cloud SQL instance)"
    printf 'postgresql+asyncpg://postgres:%s@/%s?host=/cloudsql/%s' \
        "$postgres_password" "$database_name" "$connection_name" \
        | gcloud secrets versions add cv-migration-database-url --project "$GCP_PROJECT" --data-file=-

    cat <<EOF

✓ STEP 5 complete. cv-database-url (app role) and cv-migration-database-url
  (superuser) are stored.

  Runtime SA read access for both is granted by terraform — add
  "cv-migration-database-url" to api_core_secret_ids in terraform.tfvars
  (see terraform.tfvars.example) if it is not already there, then
  terraform apply.

  api-core reads DATABASE_URL / MIGRATION_DATABASE_URL via the secret
  bindings (terraform.tfvars services.api-core.secrets). The next api-core
  revision (terraform apply, or the next deploy-app.yml release) runs
  \`alembic upgrade head\` automatically at startup (main.py lifespan,
  ADR-023) — no separate manual migration step.

  Force a restart now instead of waiting for the next release:

    gcloud run services update api-core --project $GCP_PROJECT --region $GCP_REGION \\
      --update-secrets DATABASE_URL=cv-database-url:latest,MIGRATION_DATABASE_URL=cv-migration-database-url:latest

Next: STEP 5b (bootstrap-app-role), then STEP 6 (upload-cv)

EOF
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5b: Strip BYPASSRLS from cv_app (after bootstrap-database-url)
# ─────────────────────────────────────────────────────────────────────────────
# Cloud SQL grants every google_sql_user membership of cloudsqlsuperuser,
# which carries BYPASSRLS — so cv_app starts out able to bypass row-level
# security. api-core's verify_rls_enforced() refuses to start against such a
# role (services/portfolio/tenancy.py), so this step is required, not optional.
#
# Connects through the Cloud SQL Auth Proxy using the postgres superuser
# credentials already stored in cv-migration-database-url by STEP 5, and runs
# the same statements documented in scripts/postgres-init/10-app-role.sql
# (the local-dev equivalent, run automatically there via docker-entrypoint-initdb.d).
bootstrap_app_role() {
    require_project
    log "STEP 5b: Strip BYPASSRLS/SUPERUSER from cv_app on Cloud SQL"

    command -v psql >/dev/null 2>&1 \
        || die "psql not found — install the postgresql client (e.g. 'brew install libpq' or 'apt install postgresql-client')."

    local instance_name="${CLOUDSQL_INSTANCE:-cv-postgres}"
    local proxy_port="${CLOUDSQL_PROXY_PORT:-5433}"
    local connection_name
    connection_name="$(gcloud sql instances describe "$instance_name" \
        --project "$GCP_PROJECT" --format 'value(connectionName)')" \
        || die "Cloud SQL instance '$instance_name' not found — run terraform apply first (STEP 4)."

    # postgresql+asyncpg://postgres:<password>@/<database>?host=/cloudsql/<connection>
    # Neither this parse nor bootstrap-database-url's construction of the URL
    # percent-encodes the password, so POSTGRES_PASSWORD must not contain
    # '@', '#', '/', or '?' — the same constraint cv-db-password already had.
    local migration_url postgres_password database_name
    migration_url="$(gcloud secrets versions access latest --secret=cv-migration-database-url --project "$GCP_PROJECT")" \
        || die "cv-migration-database-url has no version yet — run bootstrap-database-url first (STEP 5)."
    postgres_password="$(printf '%s' "$migration_url" | sed -E 's#^[^:]+://postgres:([^@]+)@.*#\1#')"
    database_name="$(printf '%s' "$migration_url" | sed -E 's#.*/([^/?]+)\?.*#\1#')"
    [[ -n "$postgres_password" && -n "$database_name" ]] \
        || die "Could not parse the postgres password/database out of cv-migration-database-url."

    log "  Starting the Cloud SQL Auth Proxy on 127.0.0.1:$proxy_port"
    docker run --rm -d --name cv-sql-proxy-bootstrap \
        --user "$(id -u):$(id -g)" \
        -v "$HOME/.config/gcloud:/config/gcloud:ro" \
        -e GOOGLE_APPLICATION_CREDENTIALS=/config/gcloud/application_default_credentials.json \
        -p "127.0.0.1:${proxy_port}:5432" \
        gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14.0 \
        "$connection_name" --address 0.0.0.0 >/dev/null
    trap 'docker rm -f cv-sql-proxy-bootstrap >/dev/null 2>&1 || true' EXIT

    log "  Waiting for the proxy to accept connections"
    local attempt
    for attempt in $(seq 1 30); do
        PGPASSWORD="$postgres_password" psql -h 127.0.0.1 -p "$proxy_port" -U postgres \
            -d "$database_name" -tAc 'SELECT 1' >/dev/null 2>&1 && break
        [ "$attempt" -eq 30 ] && die "Cloud SQL Auth Proxy never became ready on 127.0.0.1:$proxy_port"
        sleep 1
    done

    log "  Applying ALTER ROLE / GRANT statements to cv_app"
    PGPASSWORD="$postgres_password" psql -h 127.0.0.1 -p "$proxy_port" -U postgres -d "$database_name" <<'SQL'
ALTER ROLE cv_app NOSUPERUSER NOBYPASSRLS;
REVOKE cloudsqlsuperuser FROM cv_app;

GRANT USAGE ON SCHEMA public TO cv_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cv_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cv_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cv_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO cv_app;
SQL

    log "  Verifying"
    local verify_row
    verify_row="$(PGPASSWORD="$postgres_password" psql -h 127.0.0.1 -p "$proxy_port" -U postgres -d "$database_name" \
        -tAc "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'cv_app'")"
    [ "$verify_row" = "f|f" ] \
        || die "cv_app still has rolsuper/rolbypassrls set (got: $verify_row) — check for a lingering cloudsqlsuperuser grant."

    cat <<EOF

✓ STEP 5b complete. cv_app has neither SUPERUSER nor BYPASSRLS — row-level
  security now applies to it. api-core's verify_rls_enforced() will accept
  it at startup.

Next: STEP 6 (upload-cv)

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
# STEP 6: Upload CV data — publish cv.json to GCS
# ─────────────────────────────────────────────────────────────────────────────
upload_cv() {
    require_project
    log "STEP 6: Upload CV data (after terraform apply)"

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
    bootstrap-database-url) bootstrap_database_url ;;
    bootstrap-app-role) bootstrap_app_role ;;
    upload-cv)        upload_cv ;;
    verify)           verify ;;
    *)                sed -n '2,30p' "$0"; exit 1 ;;
esac
