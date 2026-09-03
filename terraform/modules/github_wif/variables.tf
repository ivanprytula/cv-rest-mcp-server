variable "project" {
  description = "GCP project ID"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in owner/repo format (e.g., ivanprytula/cv-rest-mcp-server)"
  type        = string
}

variable "deployer_sa_email" {
  description = "Email of the GCP service account that GitHub will impersonate"
  type        = string
}
