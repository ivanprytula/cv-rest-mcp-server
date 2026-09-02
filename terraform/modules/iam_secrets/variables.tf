variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Secret Manager replication"
  type        = string
  default     = "europe-west1"
}

variable "api_core_secret_ids" {
  description = "Secret Manager secret IDs api-core reads at runtime (beyond jwt_signing_secret_id). Secrets are created by scripts/deploy-cloud-run.sh bootstrap-secrets; this only grants the runtime SA read access."
  type        = list(string)
  default     = []
}

variable "jwt_signing_secret_id" {
  description = "Secret Manager secret ID for JWT signing key (empty = skip IAM binding). Secret itself is created by scripts/deploy-cloud-run.sh bootstrap-secrets."
  type        = string
  default     = ""
}
