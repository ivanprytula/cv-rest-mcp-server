locals {
  domain = format("storage.googleapis.com/%s", google_storage_bucket.bucket.name)
}

# Serving static assets via a backend bucket + Cloud CDN requires the origin to
# allow unauthenticated reads; the LB/CDN edge is then the only public front.
# checkov skips below are INTENTIONAL and required by the CDN design:
#  - CKV_GCP_114: public_access_prevention=enforced would BREAK the allUsers read
#    the CDN origin needs, so it cannot be set on this bucket.
#  - CKV_GCP_62: access-logging to a second log bucket is skipped in this
#    learning config for simplicity (re-enable by adding a logging block).
#  - CKV_GCP_78 is handled by the versioning block below.
#checkov:skip=CKV_GCP_114: public_access_prevention would break the CDN origin read
#checkov:skip=CKV_GCP_62: no dedicated log bucket in this learning config
resource "google_storage_bucket" "bucket" {
  name                        = var.name
  project                     = var.project
  location                    = var.location
  force_destroy               = false
  uniform_bucket_level_access = true
  labels                      = var.labels

  versioning {
    enabled = true
  }

  cors {
    origin          = var.cors_origins
    method          = ["GET", "HEAD", "OPTIONS"]
    response_header = ["Content-Type", "Cache-Control"]
    max_age_seconds = 3600
  }

  # This bucket serves the live site via Cloud CDN — objects never fully
  # expire, only superseded (non-current) versions are pruned, keeping just
  # enough history for a quick rollback of a bad deploy.
  lifecycle_rule {
    condition {
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  # Failed multipart uploads leave billed-but-unusable data behind.
  lifecycle_rule {
    condition {
      age        = 7
      with_state = "ANY"
    }
    action {
      type = "AbortIncompleteMultipartUpload"
    }
  }
}

#checkov:skip=CKV_GCP_28: public CDN origin is the intended access model (backend bucket)
resource "google_storage_bucket_iam_member" "public_read" {
  count  = var.public_read ? 1 : 0
  bucket = google_storage_bucket.bucket.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
