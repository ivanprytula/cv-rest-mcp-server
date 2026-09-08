variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "location" {
  description = "Firestore location id (multi-region, e.g. \"eur3\", or a single region matching var.region elsewhere in this project). Firestore location ids don't always match Cloud Run region names 1:1 — check `gcloud firestore locations list`."
  type        = string
}

variable "runtime_service_account_emails" {
  description = "Service account emails granted roles/datastore.user (api-core and the ATS refresh trigger — both construct GapService, which reads/writes JD documents)."
  type        = list(string)
}
