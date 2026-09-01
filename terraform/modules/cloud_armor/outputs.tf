output "security_policy_id" {
  description = "Cloud Armor security policy resource ID"
  value       = google_compute_security_policy.cdn_protection.id
}

output "security_policy_name" {
  description = "Cloud Armor security policy name"
  value       = google_compute_security_policy.cdn_protection.name
}
