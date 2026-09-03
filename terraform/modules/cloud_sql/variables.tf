variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Cloud SQL instance region"
  type        = string
}

variable "instance_name" {
  description = "Cloud SQL instance name (globally unique per project; cannot be reused for ~7 days after deletion)."
  type        = string
  default     = "cv-postgres"
}

variable "tier" {
  description = "Machine tier. db-f1-micro is the cheapest viable option for this workload's size."
  type        = string
  default     = "db-f1-micro"
}

variable "disk_size_gb" {
  description = "Initial disk size in GB. disk_autoresize handles growth beyond this."
  type        = number
  default     = 10
}

variable "backups_enabled" {
  description = "Enable automated daily backups."
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Block `terraform destroy`/instance deletion at the GCP API level. Keep true until the PR6 file-fallback retirement window (14 days of confirmed Postgres-only operation) has passed."
  type        = bool
  default     = true
}

variable "database_name" {
  description = "Application database name."
  type        = string
  default     = "cv_portfolio"
}

variable "database_user" {
  description = "Application database user."
  type        = string
  default     = "cv_app"
}

variable "db_password_secret_id" {
  description = "Secret Manager secret ID holding the DB user password. Secret + version are created by scripts/deploy-cloud-run.sh bootstrap_secrets(), never in .tfvars/state."
  type        = string
}
