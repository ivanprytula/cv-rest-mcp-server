variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "name_prefix" {
  description = "Name prefix for Cloud Armor policy"
  type        = string
  default     = "cdn-armor"
}

variable "rate_limit_count" {
  description = "Max requests allowed in the interval before rate limiting kicks in"
  type        = number
  default     = 100
}

variable "rate_limit_interval_sec" {
  description = "Time interval (seconds) for rate limit count"
  type        = number
  default     = 60
}

variable "attach_to_proxy" {
  description = "Whether to create/attach to HTTPS proxy (set false if proxy already exists and managed separately)"
  type        = bool
  default     = false
}

variable "url_map_id" {
  description = "URL map resource ID to attach security policy to"
  type        = string
  default     = null
}

variable "ssl_certificates" {
  description = "List of SSL certificate resource IDs"
  type        = list(string)
  default     = []
}

variable "ssl_policy_id" {
  description = "SSL policy resource ID"
  type        = string
  default     = null
}
