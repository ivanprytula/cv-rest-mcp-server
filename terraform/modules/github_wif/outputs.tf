output "workload_identity_pool_name" {
  description = "Full name of the Workload Identity Pool"
  value       = google_iam_workload_identity_pool.github.name
}

output "workload_identity_provider" {
  description = "Full name of the OIDC provider (use in GitHub WIF_PROVIDER secret)"
  value       = "${google_iam_workload_identity_pool.github.name}/providers/gh-actions"
  sensitive   = true
}
