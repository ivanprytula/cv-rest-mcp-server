variable "name" {
  description = "Cloud Run service name (also the image tag and '-' runtime SA suffix)."
  type        = string
}

variable "project" {
  description = "Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Cloud Run region."
  type        = string
}

variable "image" {
  description = "Container image URI, e.g. gcr.io/PROJECT/SERVICE:latest."
  type        = string
}

variable "service_account_email" {
  description = "Runtime service account email for the service."
  type        = string
}

variable "allow_unauthenticated" {
  description = "Allow unauthenticated invocation. The LB edge authenticates NEG backends regardless; worker/private services should set false."
  type        = bool
  default     = true
}

variable "env_vars" {
  description = "Environment variables set on the service (--set-env-vars style)."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Secret Manager references: mount_name -> { secret_id, version }."
  type = map(object({
    secret_id = string
    version   = string
  }))
  default = {}
}

variable "cpu" {
  description = "vCPU allocation (1 or higher)."
  type        = number
  default     = 1
}

variable "memory" {
  description = "Memory limit, e.g. '512Mi'."
  type        = string
  default     = "512Mi"
}

variable "max_instances" {
  description = "Maximum number of running instances."
  type        = number
  default     = 1
}

variable "min_instances" {
  description = "Minimum number of warm instances."
  type        = number
  default     = 0
}

variable "execution_environment" {
  description = "EXECUTION_ENVIRONMENT_GEN2 (default) or EXECUTION_ENVIRONMENT_GEN1."
  type        = string
  default     = "EXECUTION_ENVIRONMENT_GEN2"
}

variable "timeout_seconds" {
  description = "Request timeout in seconds."
  type        = number
  default     = 300
}

variable "ingress" {
  description = "Ingress setting: INGRESS_TRAFFIC_ALL/INGRESS_TRAFFIC_INTERNAL_ONLY/INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER."
  type        = string
  default     = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
}

variable "cloud_sql_instances" {
  description = "Cloud SQL instance connection names (PROJECT:REGION:INSTANCE) to mount via the native Cloud Run v2 Auth Proxy socket — no Serverless VPC Access connector needed. Empty = no Cloud SQL volume mounted."
  type        = list(string)
  default     = []
}

variable "labels" {
  description = "GCP resource labels for cost attribution (e.g. { service = \"api-core\", environment = \"production\" })."
  type        = map(string)
  default     = {}
}
