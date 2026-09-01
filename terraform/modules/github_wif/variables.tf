variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in owner/repo format (e.g., ivanprytula/cv-rest-mcp-server)"
  type        = string
}

variable "github_aud" {
  description = "GitHub token audience (typically matches repository URL)"
  type        = string
  default     = "https://github.com"
}

variable "deployer_sa_email" {
  description = "Email of the GCP service account that GitHub will impersonate"
  type        = string
}
