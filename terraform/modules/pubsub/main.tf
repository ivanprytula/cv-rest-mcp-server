# PostingChanged events decouple ATS-sync (fast, inline) from gap analysis
# (Phase 3f). See services/portfolio/events/pubsub_publisher.py.
#
# A dead-letter topic, not a bespoke retry loop: Pub/Sub's own subscription
# retry policy plus DLQ forwarding covers "the subscriber failed N times",
# so the analysis-worker service (Phase 3f PR3) doesn't hand-roll it.
# CKV_GCP_83 (CSEK) is skipped repo-wide in .pre-commit-config.yaml,
# same reasoning as CKV_GCP_84: Google-managed encryption at rest already
# applies by default; CSEK would add Cloud KMS key management overhead
# with no corresponding threat model here.
resource "google_pubsub_topic" "posting_changed" {
  project = var.project
  name    = "posting-changed"
  labels  = var.labels
}

resource "google_pubsub_topic" "posting_changed_dlq" {
  project = var.project
  name    = "posting-changed-dlq"
  labels  = var.labels
}

resource "google_project_iam_member" "publisher_access" {
  for_each = toset(var.publisher_service_account_emails)
  project  = var.project
  role     = "roles/pubsub.publisher"
  member   = "serviceAccount:${each.value}"
}
