output "api_core_runtime_sa_email" {
  description = "api-core service account email"
  value       = google_service_account.api_core_runtime.email
}

output "spa_origin_runtime_sa_email" {
  description = "spa-origin service account email"
  value       = contains(keys(var.services), "spa-origin") ? google_service_account.spa_origin_runtime[0].email : null
}

output "api_games_runtime_sa_email" {
  description = "api-games service account email"
  value       = contains(keys(var.services), "api-games") ? google_service_account.api_games_runtime[0].email : null
}

output "ats_refresh_trigger_runtime_sa_email" {
  description = "ATS refresh trigger service account email"
  value       = contains(keys(var.services), "ats-refresh-trigger") ? google_service_account.ats_refresh_trigger_runtime[0].email : null
}

output "analysis_worker_runtime_sa_email" {
  description = "Analysis worker service account email"
  value       = contains(keys(var.services), "analysis-worker") ? google_service_account.analysis_worker_runtime[0].email : null
}

output "deployer_sa_email" {
  description = "Email of the CI/CD deployer service account"
  value       = google_service_account.deployer.email
}

output "cv_images_repo_url" {
  description = "Artifact Registry docker repo path, e.g. europe-west1-docker.pkg.dev/PROJECT/cv-images"
  value       = "${google_artifact_registry_repository.cv_images.location}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.cv_images.repository_id}"
}
