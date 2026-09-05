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

variable "enable_cloud_sql" {
  description = "Bind roles/cloudsql.client to the api-core and ats-refresh-trigger runtime SAs. Mirrors the root module's enable_cloud_sql flag; a plain bool (not a connection-name string) so `count` is known at plan time even before the cloud_sql module's instance exists."
  type        = bool
  default     = false
}

variable "database_url_secret_id" {
  description = "Secret Manager secret ID for the Postgres connection string (empty = skip IAM binding). Granted to the ATS refresh trigger's runtime SA — it needs DATABASE_URL directly, unlike api_core_secret_ids which is a list keyed for api-core."
  type        = string
  default     = ""
}

variable "labels" {
  description = "GCP resource labels for cost attribution (e.g. { service = \"iam-secrets\", environment = \"production\" })."
  type        = map(string)
  default     = {}
}
