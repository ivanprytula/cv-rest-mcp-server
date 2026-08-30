output "bucket_name" {
  description = "Private uploads bucket name."
  value       = google_storage_bucket.uploads.name
}

output "self_link" {
  description = "Bucket self-link."
  value       = google_storage_bucket.uploads.id
}
