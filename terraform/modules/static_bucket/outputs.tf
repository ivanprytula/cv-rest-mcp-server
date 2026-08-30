output "bucket_name" {
  description = "GCS bucket name (used as the backend bucket / path_routes bucket)."
  value       = google_storage_bucket.bucket.name
}

output "self_link" {
  description = "Bucket self-link."
  value       = google_storage_bucket.bucket.id
}

output "public_url" {
  description = "Public object base URL (direct GCS; normally reached through the LB/CDN)."
  value       = "https://${local.domain}"
}
