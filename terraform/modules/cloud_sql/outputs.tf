output "connection_name" {
  description = "Cloud SQL instance connection name (PROJECT:REGION:INSTANCE) for the Cloud Run Auth Proxy socket mount."
  value       = google_sql_database_instance.instance.connection_name
}

output "instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.instance.name
}

output "database_name" {
  description = "Application database name."
  value       = google_sql_database.app.name
}

output "database_user" {
  description = "Application database user."
  value       = google_sql_user.app.name
}
