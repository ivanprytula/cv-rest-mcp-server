variable "name" {
  description = "Bucket name (must be globally unique)."
  type        = string
}

variable "project" {
  description = "Google Cloud project ID."
  type        = string
}

variable "location" {
  description = "Multi-region (e.g. EU) or region for the bucket. CDN serves globally regardless."
  type        = string
  default     = "EU"
}

variable "public_read" {
  description = "Grant allUsers objectViewer. Required for a google_compute_backend_bucket origin (the LB proxies the bucket on the client's behalf). Safe for static assets; the CDN front is the access point."
  type        = bool
  default     = true
}

variable "cors_origins" {
  description = "Allowed CORS origins for the SPA to fetch loaded assets (e.g. https://app.<apex>)."
  type        = list(string)
  default     = []
}
