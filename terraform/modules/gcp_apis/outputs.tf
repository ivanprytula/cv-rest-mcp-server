output "apis_enabled" {
  description = "List of enabled APIs"
  value = [
    google_project_service.cloudresourcemanager.service,
    google_project_service.compute.service,
    google_project_service.iam.service,
    google_project_service.storage.service,
    google_project_service.run.service,
    google_project_service.dns.service,
    google_project_service.secretmanager.service,
    google_project_service.cloudbuild.service,
  ]
}
