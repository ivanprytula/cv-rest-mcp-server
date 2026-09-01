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

output "jwt_signing_secret_id" {
  description = "Secret Manager secret ID for JWT signing key (or empty if not created)"
  value       = try(google_secret_manager_secret.jwt_signing_key[0].id, "")
}

output "refresh_token_pepper_secret_id" {
  description = "Secret Manager secret ID for refresh token pepper (or empty if not created)"
  value       = try(google_secret_manager_secret.refresh_token_pepper[0].id, "")
}

output "deployer_sa_email" {
  description = "Email of the CI/CD deployer service account"
  value       = google_service_account.deployer.email
}
