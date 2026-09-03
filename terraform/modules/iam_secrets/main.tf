# IAM roles, service accounts, and Secret Manager secrets.
# Centralizes identity and access management away from shell scripts.

resource "google_service_account" "api_core_runtime" {
  account_id   = "api-core-runtime"
  display_name = "api-core Cloud Run service account"
  project      = var.project
}

resource "google_service_account" "spa_origin_runtime" {
  account_id   = "spa-origin-runtime"
  display_name = "spa-origin Cloud Run service account"
  project      = var.project
}

resource "google_service_account" "api_games_runtime" {
  account_id   = "api-games-runtime"
  display_name = "api-games Cloud Run service account"
  project      = var.project
}

resource "google_service_account" "deployer" {
  account_id   = "deployer"
  display_name = "CI/CD deployer service account"
  project      = var.project
}

# Deployer requires Cloud Run admin + Secret Manager access
resource "google_project_iam_member" "deployer_run_admin" {
  project = var.project
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_secret_accessor" {
  project = var.project
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# terraform apply grants api_core_secret_ids read access to api-core-runtime
# (google_secret_manager_secret_iam_member below) — that requires setIamPolicy
# on the secret itself, which secretAccessor above does not include.
resource "google_project_iam_member" "deployer_secret_admin" {
  project = var.project
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Deployer runs `terraform plan`, which reads existing state for
# google_project_service (gcp_apis), google_iam_workload_identity_pool
# (github_wif), and bucket IAM policies (static_bucket, uploads) — each of
# these three roles covers the read (and, where relevant, write) permission
# those resource types require during plan/apply.
resource "google_project_iam_member" "deployer_service_usage_admin" {
  project = var.project
  role    = "roles/serviceusage.serviceUsageAdmin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_workload_identity_pool_admin" {
  project = var.project
  role    = "roles/iam.workloadIdentityPoolAdmin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_storage_admin" {
  project = var.project
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# terraform plan refreshes the google_project_iam_member and
# google_service_account_iam_member resources this module manages, which
# requires reading project and service-account IAM policies.
# securityReviewer is read-only across IAM (no grant/revoke powers).
resource "google_project_iam_member" "deployer_security_reviewer" {
  project = var.project
  role    = "roles/iam.securityReviewer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# The dns module manages the zone and its record sets, so the deployer
# needs write access, not just read.
resource "google_project_iam_member" "deployer_dns_admin" {
  project = var.project
  role    = "roles/dns.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# deploy-app.yml submits image builds via `gcloud builds submit`.
resource "google_project_iam_member" "deployer_cloudbuild_builder" {
  project = var.project
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Deployer must pull images from GCR (Artifact Registry-backed) for
# `gcloud run deploy` to fetch the container being deployed.
resource "google_project_iam_member" "deployer_artifact_registry_reader" {
  project = var.project
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Regional Artifact Registry repo for app images, replacing the legacy
# gcr.io host. Deploy pipeline pushes here directly (deploy-app.yml) and
# `gcloud run deploy` pulls from here.
resource "google_artifact_registry_repository" "cv_images" {
  project       = var.project
  location      = var.region
  repository_id = "cv-images"
  format        = "DOCKER"
  description   = "Application images (api-core, api-games, spa-origin)"
}

resource "google_artifact_registry_repository_iam_member" "deployer_cv_images_writer" {
  project    = var.project
  location   = google_artifact_registry_repository.cv_images.location
  repository = google_artifact_registry_repository.cv_images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

# Deployer runs `terraform apply` in CI, which reads the serverless NEGs
# (created alongside each Cloud Run service) as part of refreshing state.
# compute.networkViewer lacks networkEndpointGroups.get; compute.viewer covers it.
resource "google_project_iam_member" "deployer_compute_viewer" {
  project = var.project
  role    = "roles/compute.viewer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# CI/CD deployer needs to assign runtime SAs to Cloud Run services.
# Scoped to deployer SA only; acceptable trade-off for CI/CD automation.
resource "google_project_iam_member" "deployer_actAs" {
  project = var.project
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Project-level serviceAccountUser above should cover actAs, but Cloud Run
# deploy checks have been observed to require a direct binding on the
# target runtime SA. Explicit bindings avoid IAM-policy-inheritance gaps.
resource "google_service_account_iam_member" "deployer_actas_api_core" {
  service_account_id = google_service_account.api_core_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_actas_spa_origin" {
  service_account_id = google_service_account.spa_origin_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_actas_api_games" {
  service_account_id = google_service_account.api_games_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# API-core requires read access to CV data bucket + logging
resource "google_project_iam_member" "api_core_storage" {
  project = var.project
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.api_core_runtime.email}"
}

resource "google_project_iam_member" "api_core_logging" {
  project = var.project
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.api_core_runtime.email}"
}

resource "google_project_iam_member" "api_core_gcr_pull" {
  project = var.project
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.api_core_runtime.email}"
}

resource "google_project_iam_member" "spa_origin_gcr_pull" {
  project = var.project
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.spa_origin_runtime.email}"
}

resource "google_project_iam_member" "api_games_gcr_pull" {
  project = var.project
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.api_games_runtime.email}"
}

# Runtime SAs pull images from the new cv-images Artifact Registry repo.
resource "google_artifact_registry_repository_iam_member" "api_core_cv_images_reader" {
  project    = var.project
  location   = google_artifact_registry_repository.cv_images.location
  repository = google_artifact_registry_repository.cv_images.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.api_core_runtime.email}"
}

resource "google_artifact_registry_repository_iam_member" "spa_origin_cv_images_reader" {
  project    = var.project
  location   = google_artifact_registry_repository.cv_images.location
  repository = google_artifact_registry_repository.cv_images.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.spa_origin_runtime.email}"
}

resource "google_artifact_registry_repository_iam_member" "api_games_cv_images_reader" {
  project    = var.project
  location   = google_artifact_registry_repository.cv_images.location
  repository = google_artifact_registry_repository.cv_images.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.api_games_runtime.email}"
}

# Cloud SQL Auth Proxy socket mount (Phase 2) requires the runtime SA to
# hold cloudsql.client, which grants the API calls the proxy makes on the
# service's behalf to establish the encrypted tunnel to the instance.
# Gated on the bool (not a connection-name string) so `count` is known at
# plan time even on a from-scratch apply, before the cloud_sql module's
# instance (and its connection_name output) exists yet.
resource "google_project_iam_member" "api_core_cloudsql_client" {
  count   = var.enable_cloud_sql ? 1 : 0
  project = var.project
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api_core_runtime.email}"
}

# Secret Manager access for JWT signing key (Phase 1c+)
resource "google_secret_manager_secret_iam_member" "api_core_jwt_key" {
  count     = var.jwt_signing_secret_id != "" ? 1 : 0
  secret_id = var.jwt_signing_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api_core_runtime.email}"
}

# Every other secret api-core reads at runtime. The secrets themselves (and
# their versions) are created by scripts/deploy-cloud-run.sh bootstrap-secrets;
# this only grants read access. A secret listed here must exist before apply.
resource "google_secret_manager_secret_iam_member" "api_core_secrets" {
  for_each = toset(var.api_core_secret_ids)

  project   = var.project
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api_core_runtime.email}"
}

# Cloud Build permissions (shared across all builders)
resource "google_project_iam_member" "cloud_build_artifact_writer" {
  project = var.project
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

resource "google_project_iam_member" "cloud_build_storage_reader" {
  project = var.project
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

resource "google_project_iam_member" "cloud_build_logging" {
  project = var.project
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

# Secrets (cv-jwt-signing-key, cv-refresh-token-pepper) and their versions are
# created by scripts/deploy-cloud-run.sh bootstrap-secrets — not here. This
# module only binds IAM access to secret IDs it assumes already exist.

# Data source to fetch current project info
data "google_project" "current" {
  project_id = var.project
}
