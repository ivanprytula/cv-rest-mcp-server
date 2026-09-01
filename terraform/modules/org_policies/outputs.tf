output "uniform_bucket_level_access_policy_id" {
  description = "Organization Policy ID for uniform bucket-level access enforcement"
  value       = google_org_policy_policy.uniform_bucket_level_access.name
}

output "deny_bucket_public_access_policy_id" {
  description = "Organization Policy ID for deny-public-access enforcement"
  value       = google_org_policy_policy.deny_bucket_public_access.name
}
