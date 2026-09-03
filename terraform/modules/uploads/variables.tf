variable "name" {
  description = "Bucket name (globally unique)."
  type        = string
}

variable "project" {
  description = "Google Cloud project ID."
  type        = string
}

variable "location" {
  description = "Bucket location."
  type        = string
  default     = "EU"
}

# Object key prefixes that only the app service account may write/read.
# The UI never touches the bucket directly; it uses server-generated V4 signed
# URLs scoped to a single object under one of these prefixes.
variable "write_prefixes" {
  description = "Allowed object prefixes for signed-url PUTs (e.g. [\"avatars/\", \"photos/\"])."
  type        = list(string)
  default     = []
}

# Service account (email) that may read objects server-side (avatar/photo fetch
# from an auth-protected endpoint). Empty = app reads via signed URLs only.
variable "app_sa" {
  description = "Service account email allowed server-side object access."
  type        = string
  default     = ""
}

variable "labels" {
  description = "GCP resource labels for cost attribution (e.g. { service = \"uploads\", environment = \"production\" })."
  type        = map(string)
  default     = {}
}
