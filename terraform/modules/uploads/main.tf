# Private upload bucket for user-generated content (avatars, photos).
# - public_access_prevention=enforced + uniform access: NO anonymous read/write.
# - no public IAM bindings at all.
# - writes only ever happen via server-generated V4 signed URLs (see recipe);
#   the app service account owns the objects and reads them server-side or via
#   signed GET URLs from an auth-protected endpoint.
resource "google_storage_bucket" "uploads" {
  name                        = var.name
  project                     = var.project
  location                    = var.location
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }
}

# The app service account is the only ambient identity with object access.
# Signed URLs are generated with this SA's credentials server-side.
resource "google_storage_bucket_iam_member" "app_sa" {
  count  = var.app_sa != "" ? 1 : 0
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.app_sa}"
}

# Optional: scope write_prefixes to the app SA only via signed objects — the
# signed URL feature itself already enforces object scope, so no extra IAM is
# needed for prefixes; this is a coding convention on the endpoint, not an IAM
# rule. Kept here as documentation of the intended object layout.
#checkov:skip=CKV_GCP_62: access-logging to a second log bucket skipped for simplicity (learning config)
