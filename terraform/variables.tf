variable "project_id" {
  description = "Google Cloud project ID (single managed environment)."
  type        = string
}

variable "region" {
  description = "Region for regional resources (Cloud Run, serverless NEGs)."
  type        = string
  default     = "europe-west1"
}

variable "apex_domain" {
  description = "Apex domain, e.g. example.com. Placeholder must be overridden via terraform.tfvars."
  type        = string
}

variable "dns_name" {
  description = "DNS zone name (apex_domain + trailing dot). Empty = derive from apex_domain."
  type        = string
  default     = ""
}

variable "create_dns_zone" {
  description = "Create and own the Cloud DNS zone. Set false if DNS stays at the current registrar; then wire the LB IP manually."
  type        = bool
  default     = true
}

variable "subdomains" {
  description = "A records to create toward the LB IP; '@' = apex. www/api/app/games are the Phase 1a set."
  type        = list(string)
  default     = ["@", "www", "api", "app", "games"]
}

# Workloads are the DISTINCT Cloud Run services. www and api can both route to
# the one api-core workload — see host_routing.
variable "services" {
  description = <<-EOT
    Workloads to deploy as distinct Cloud Run services, keyed by workload name.
      <workload> = {
        image                 = "gcr.io/PROJECT/SERVICE:latest"
        service_account       = "<runtime SA email>"
        allow_unauthenticated = bool
        env_vars              = { NAME = value }
        secrets               = { NAME = { secret_id = ..., version = ... } }
        max_instances         = int
        min_instances         = int
        memory                = "512Mi"
      }
  EOT
  type = map(object({
    image                 = string
    service_account       = string
    allow_unauthenticated = bool
    env_vars              = optional(map(string), {})
    secrets               = optional(map(object({ secret_id = string, version = string })), {})
    max_instances         = optional(number, 1)
    min_instances         = optional(number, 0)
    memory                = optional(string, "512Mi")
  }))
}

# hostname -> workload name. Multiple hosts may map to one workload (e.g. both
# www.<apex> and api.<apex> -> "api-core").
variable "host_routing" {
  description = "Map of fully-qualified hostname -> workload name from `services`."
  type        = map(string)
}

# Private upload bucket for user content (avatars/photos). Signed-URL only writes.
# Kept commented with the module (main.tf) — uncomment both together to provision.
# variable "uploads" {
#   description = <<-EOT
#     Optional private upload bucket for user content (avatars/photos). null = skip.
#       bucket_name  = GCS bucket name (globally unique), e.g. "myproj-uploads"
#       location     = bucket location
#       app_sa       = app service account email allowed server-side object access
#       write_prefixes = allowed object prefixes for signed-url PUTs
#   EOT
#   type = object({
#     bucket_name     = string
#     location        = string
#     app_sa          = string
#     write_prefixes  = list(string)
#   })
#   default = null
# }

variable "static_assets" {
  description = <<-EOT
    Optional Cloud CDN static-asset serving. null = skip.
      enabled       = create the GCS bucket + backend bucket + URL-map path rule
      bucket_name   = GCS bucket name (globally unique), e.g. "myproj-static"
      location      = bucket location (EU / US / multi-region)
      host          = FQDN host that must ALREADY exist in host_routing (CDN is
                      prefix-routed INSIDE this host)
      prefix        = URL prefix routed to the bucket, e.g. "/assets/"
      cors_origins  = allowed origins for the SPA to fetch loaded assets
  EOT
  type = object({
    enabled      = bool
    bucket_name  = string
    location     = string
    host         = string
    prefix       = string
    cors_origins = list(string)
  })
  default = null
}

# IAM and Secrets (managed by iam_secrets module)
variable "jwt_signing_secret_id" {
  description = "Existing Secret Manager secret ID for JWT signing key (create separately if needed)"
  type        = string
  default     = ""
}

variable "jwt_signing_key_value" {
  description = "JWT signing key value to create/update in Secret Manager (sensitive, leave empty to skip)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "refresh_token_pepper_value" {
  description = "Refresh token pepper value to create/update in Secret Manager (sensitive, leave empty to skip)"
  type        = string
  sensitive   = true
  default     = ""
}

# GitHub Workload Identity Federation
variable "github_repo" {
  description = "GitHub repository in owner/repo format (e.g., ivanprytula/cv-rest-mcp-server)"
  type        = string
  default     = ""
}

variable "setup_github_wif" {
  description = "Set to true to create GitHub WIF (Workload Identity Federation) for CI/CD"
  type        = bool
  default     = false
}

variable "setup_org_policies" {
  description = "Set to true to enforce Organization Policies (uniform bucket access, deny-public)"
  type        = bool
  default     = false
}

# Private upload bucket for user-generated content (optional)
variable "uploads" {
  description = <<-EOT
    Private user-content upload bucket (avatars, photos). When set, creates a deny-public bucket.
      {
        bucket_name    = "myproj-uploads"
        location       = "EU"
        app_sa         = "api-core-runtime@myproj.iam.gserviceaccount.com"
        write_prefixes = ["avatars/", "photos/"]
      }
  EOT
  type = object({
    bucket_name    = string
    location       = string
    app_sa         = string
    write_prefixes = list(string)
  })
  default = null
}
