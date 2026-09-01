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

# Deployer must pull images from GCR (Artifact Registry-backed) for
# `gcloud run deploy` to fetch the container being deployed.
resource "google_project_iam_member" "deployer_artifact_registry_reader" {
  project = var.project
  role    = "roles/artifactregistry.reader"
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

# Secret Manager access for JWT signing key (Phase 1c+)
resource "google_secret_manager_secret_iam_member" "api_core_jwt_key" {
  count     = var.jwt_signing_secret_id != "" ? 1 : 0
  secret_id = var.jwt_signing_secret_id
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

# Secrets (only created if their content is provided)
# Naming aligns with deploy-cloud-run.sh convention: cv-<secret-name>
resource "google_secret_manager_secret" "jwt_signing_key" {
  count     = var.jwt_signing_key_value != "" ? 1 : 0
  secret_id = "cv-jwt-signing-key"
  project   = var.project

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "jwt_signing_key" {
  count       = var.jwt_signing_key_value != "" ? 1 : 0
  secret      = google_secret_manager_secret.jwt_signing_key[0].id
  secret_data = var.jwt_signing_key_value
}

resource "google_secret_manager_secret" "refresh_token_pepper" {
  count     = var.refresh_token_pepper_value != "" ? 1 : 0
  secret_id = "cv-refresh-token-pepper"
  project   = var.project

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "refresh_token_pepper" {
  count       = var.refresh_token_pepper_value != "" ? 1 : 0
  secret      = google_secret_manager_secret.refresh_token_pepper[0].id
  secret_data = var.refresh_token_pepper_value
}

# Data source to fetch current project info
data "google_project" "current" {
  project_id = var.project
}
