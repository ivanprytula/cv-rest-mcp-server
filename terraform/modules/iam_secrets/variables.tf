variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Secret Manager replication"
  type        = string
  default     = "europe-west1"
}

variable "jwt_signing_secret_id" {
  description = "Secret Manager secret ID for JWT signing key (empty = skip IAM binding). Secret itself is created by scripts/deploy-cloud-run.sh bootstrap-secrets."
  type        = string
  default     = ""
}
