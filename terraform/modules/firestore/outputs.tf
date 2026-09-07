output "database_name" {
  description = "Firestore database name (\"(default)\")."
  value       = google_firestore_database.default.name
}
