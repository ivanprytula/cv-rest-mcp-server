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
  description = "Secret Manager secret ID for JWT signing key (empty = skip IAM binding)"
  type        = string
  default     = ""
}

variable "jwt_signing_key_value" {
  description = "JWT signing key value (empty = skip secret creation)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "refresh_token_pepper_value" {
  description = "Refresh token pepper value (empty = skip secret creation)"
  type        = string
  sensitive   = true
  default     = ""
}
