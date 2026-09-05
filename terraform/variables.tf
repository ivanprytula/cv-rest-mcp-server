variable "project_id" {
  description = "Google Cloud project ID (single managed environment)."
  type        = string
}

variable "region" {
  description = "Region for regional resources (Cloud Run, serverless NEGs)."
  type        = string
  default     = "europe-west1"
}

variable "environment" {
  description = "Deployment environment, applied as the 'environment' GCP label on every labelable resource for cost attribution (e.g. production, staging)."
  type        = string
  default     = "production"
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
        ingress               = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"  # optional
        command               = []                                        # optional
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
    # Internal-only services (e.g. the ATS refresh trigger, invoked by Cloud
    # Scheduler's OIDC token, never by the public LB) override this away
    # from the LB-routed default. See modules/cloud_run_service/variables.tf.
    ingress = optional(string, "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER")
    # Container command override — lets a second service run a different
    # entrypoint from the same image (see modules/cloud_run_service).
    command = optional(list(string), [])
  }))
}

# Manual/break-glass image-tag override, keyed by workload name (matches
# `services` keys). Routine releases go through deploy-app.yml's
# `gcloud run deploy` and never touch Terraform — this var is only for a
# manual `terraform apply -var 'image_overrides={...}'` (e.g. restoring an
# older SHA outside the normal pipeline). Empty/missing entries fall back
# to the image already set in `services`.
variable "image_overrides" {
  description = "Workload name -> image (e.g. europe-west1-docker.pkg.dev/PROJECT/cv-images/api-core:abc1234). Overrides services[key].image."
  type        = map(string)
  default     = {}
}

# hostname -> workload name. Multiple hosts may map to one workload (e.g. both
# www.<apex> and api.<apex> -> "api-core").
variable "host_routing" {
  description = "Map of fully-qualified hostname -> workload name from `services`."
  type        = map(string)
}

# Cloud SQL Postgres for the auth/user store (ADR-023 Phase 2, PR2). Defaults
# to false so this module is opt-in until Infracost has confirmed the tier
# fits the $100/month budget on a real plan against this repo's other costs.
variable "enable_cloud_sql" {
  description = "Provision the Cloud SQL Postgres instance (modules/cloud_sql) and its Cloud Run Auth Proxy wiring."
  type        = bool
  default     = false
}

# Secret container + version are script-owned (scripts/deploy-cloud-run.sh
# bootstrap_secrets(), cv-db-password) — never in .tfvars or state. This var
# only names the secret ID for modules/cloud_sql to read via data source.
variable "cloud_sql_db_password_secret_id" {
  description = "Secret Manager secret ID holding the Cloud SQL app user password."
  type        = string
  default     = "cv-db-password"
}

# Composed from cloud_sql_db_password_secret_id + the instance's connection
# name by `just deploy bootstrap-database-url` (see CLAUDE.md's Bootstrap &
# Deployment section) — script-owned like the other secrets, this only names
# the ID so the ats-refresh-trigger runtime SA can be granted read access.
variable "database_url_secret_id" {
  description = "Secret Manager secret ID holding the Postgres connection string (DATABASE_URL)."
  type        = string
  default     = "cv-database-url"
}

# Cron expression for the ATS refresh job (unix-cron, e.g. "0 */6 * * *" for
# every 6 hours). Cloud Scheduler is a general cron scheduler, not limited to
# once a day — pick whatever cadence fits; the ETag-based conditional GET in
# gaps/ats.py keeps a more frequent schedule cheap against unchanged boards.
variable "ats_refresh_schedule" {
  description = "Unix-cron expression for how often the ATS refresh trigger runs."
  type        = string
  default     = "0 8 * * *" # once daily, 08:00
}

variable "ats_refresh_timezone" {
  description = "IANA timezone for ats_refresh_schedule."
  type        = string
  default     = "Etc/UTC"
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

# IAM binding target only — secrets themselves are created by
# scripts/deploy-cloud-run.sh bootstrap-secrets, not Terraform.
variable "api_core_secret_ids" {
  description = "Additional Secret Manager secret IDs api-core reads (e.g. refresh-token pepper, first-admin password). Created by bootstrap-secrets; Terraform only grants read access."
  type        = list(string)
  default     = []
}

variable "jwt_signing_secret_id" {
  description = "Existing Secret Manager secret ID for JWT signing key (create via scripts/deploy-cloud-run.sh bootstrap-secrets)"
  type        = string
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

# Cloud Armor: DDoS/abuse protection for static CDN assets
variable "enable_cloud_armor" {
  description = "Enable Cloud Armor security policy for CDN protection"
  type        = bool
  default     = false
}

variable "cloud_armor_rate_limit_count" {
  description = "Max requests per IP before rate limiting (Cloud Armor)"
  type        = number
  default     = 100
}

variable "cloud_armor_rate_limit_interval_sec" {
  description = "Time window (seconds) for Cloud Armor rate limiting"
  type        = number
  default     = 60
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
