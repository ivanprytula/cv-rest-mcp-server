output "api_core_runtime_sa_email" {
  description = "api-core service account email"
  value       = google_service_account.api_core_runtime.email
}

output "spa_origin_runtime_sa_email" {
  description = "spa-origin service account email"
  value       = google_service_account.spa_origin_runtime.email
}

output "api_games_runtime_sa_email" {
  description = "api-games service account email"
  value       = google_service_account.api_games_runtime.email
}

output "deployer_sa_email" {
  description = "Email of the CI/CD deployer service account"
  value       = google_service_account.deployer.email
}

output "cv_images_repo_url" {
  description = "Artifact Registry docker repo path, e.g. europe-west1-docker.pkg.dev/PROJECT/cv-images"
  value       = "${google_artifact_registry_repository.cv_images.location}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.cv_images.repository_id}"
}
