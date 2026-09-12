variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "publisher_service_account_emails" {
  description = "Service account emails granted roles/pubsub.publisher (api-core and the ATS refresh trigger — both construct GapService, which publishes PostingChanged events)."
  type        = list(string)
}

variable "labels" {
  description = "GCP resource labels for cost attribution (e.g. { service = \"pubsub\" })."
  type        = map(string)
  default     = {}
}
