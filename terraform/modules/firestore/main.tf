# Firestore for raw JD documents (Phase 2b PR8). Postgres keeps only the
# relational skeleton of a job posting — see
# services/portfolio/gaps/jd_document_store.py for why the raw text and
# per-portal metadata live here instead of duplicated into both stores.
#
# Native mode (not Datastore mode): the async client library
# (google-cloud-firestore) targets native mode, and this project has no
# existing Datastore-mode usage to stay compatible with.
#
# A GCP project can have exactly one Firestore database named "(default)"
# without extra multi-database setup — this is that database. Applied
# locally as Owner, per this project's documented pattern for
# first-created resources (see other modules' bootstrap notes).
resource "google_firestore_database" "default" {
  project     = var.project
  name        = "(default)"
  location_id = var.location
  type        = "FIRESTORE_NATIVE"

  # Same rationale as Cloud SQL's deletion_protection: block the delete at
  # the GCP API level, not just terraform destroy. Raw JD documents are
  # comparatively low-value to lose (unlike the CV data or user store), so
  # this uses Terraform's default DELETE_PROTECTION_ENABLED. Revisit only if
  # this becomes a genuine "delete and recreate cleanly" workflow need.
  deletion_policy = "DELETE"
}

resource "google_project_iam_member" "jd_document_store_access" {
  for_each = toset(var.runtime_service_account_emails)
  project  = var.project
  role     = "roles/datastore.user"
  member   = "serviceAccount:${each.value}"
}
