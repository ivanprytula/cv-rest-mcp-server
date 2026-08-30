output "service_id" {
  description = "Fully qualified id of the Cloud Run service."
  value       = google_cloud_run_v2_service.service.id
}

output "service_name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.service.name
}

output "neg_id" {
  description = "Fully qualified id of the serverless NEG."
  value       = google_compute_region_network_endpoint_group.neg.id
}

output "neg_self_link" {
  description = "Self link of the serverless NEG (for the LB backend service)."
  value       = google_compute_region_network_endpoint_group.neg.self_link
}

output "neg_region" {
  description = "Region of the serverless NEG."
  value       = google_compute_region_network_endpoint_group.neg.region
}
