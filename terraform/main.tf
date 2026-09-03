provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required GCP APIs first (all other modules depend on these)
module "gcp_apis" {
  source = "./modules/gcp_apis"

  project = var.project_id
}

# Cloud SQL Postgres for the auth/user store (ADR-023 Phase 2). Infra-only in
# this PR — no service reads it yet; PR3 wires DATABASE_URL into api-core.
module "cloud_sql" {
  count      = var.enable_cloud_sql ? 1 : 0
  depends_on = [module.gcp_apis]
  source     = "./modules/cloud_sql"

  project               = var.project_id
  region                = var.region
  db_password_secret_id = var.cloud_sql_db_password_secret_id
  labels                = merge(local.base_labels, { service = "cloud-sql" })
}

# IAM, service accounts, and secrets (centralized, away from shell scripts).
# No module-level depends_on on gcp_apis: the APIs this module's resources
# actually need (iam, secretmanager, artifactregistry, cloudresourcemanager)
# are already enabled from prior applies, and a blanket module-wide
# depends_on forces even unrelated reads (data.google_project.current) to
# wait on every resource gcp_apis manages — including ones with nothing to
# do with IAM — which spuriously forces replacement of resources whose
# member/value is computed from that data source whenever gcp_apis gains a
# new resource (e.g. sqladmin in this PR triggered a false "must be
# replaced" on the cloud_build_* bindings).
module "iam_secrets" {
  source = "./modules/iam_secrets"

  project               = var.project_id
  region                = var.region
  jwt_signing_secret_id = var.jwt_signing_secret_id
  api_core_secret_ids   = var.api_core_secret_ids
  enable_cloud_sql      = var.enable_cloud_sql
  labels                = merge(local.base_labels, { service = "iam-secrets" })
}

# GitHub Workload Identity Federation for CI/CD (optional)
module "github_wif" {
  count  = var.setup_github_wif ? 1 : 0
  source = "./modules/github_wif"

  project           = var.project_id
  github_repo       = var.github_repo
  deployer_sa_email = module.iam_secrets.deployer_sa_email
}

# Organization Policies for security guardrails (optional)
module "org_policies" {
  depends_on = [module.gcp_apis]
  count      = var.setup_org_policies ? 1 : 0
  source     = "./modules/org_policies"

  project = var.project_id
}

locals {
  # Cost-attribution labels: every module merges its own `service` on top.
  #
  # Changing this needs a LOCAL `terraform apply` as Owner. It fans out to
  # cloud_sql, edge_lb's global address and iam_secrets' Artifact Registry
  # repo, and the CI deployer SA has read-only access to all three (see
  # modules/iam_secrets) — CI would 403. Label writes are set-once, so a
  # steady-state plan stays clean and CI never needs the permission.
  base_labels = {
    environment = var.environment
  }

  dns_name = var.dns_name != "" ? var.dns_name : "${var.apex_domain}."

  # One NEG backend per routed hostname -> the workload's serverless NEG.
  neg_backends = {
    for host, workload in var.host_routing :
    host => {
      type          = "neg"
      neg_self_link = module.run[workload].neg_self_link
      neg_region    = module.run[workload].neg_region
    }
  }

  # Cloud CDN path route (e.g. app.<apex>/assets/* -> static bucket).
  cdn_path_route = var.static_assets != null && var.static_assets.enabled ? {
    (var.static_assets.host) = {
      prefix = var.static_assets.prefix
      bucket = var.static_assets.bucket_name
    }
  } : {}
}

# Distinct Cloud Run workloads + serverless NEGs.
module "run" {
  source   = "./modules/cloud_run_service"
  for_each = var.services

  name                  = each.key
  project               = var.project_id
  region                = var.region
  image                 = lookup(var.image_overrides, each.key, each.value.image)
  service_account_email = each.value.service_account
  allow_unauthenticated = each.value.allow_unauthenticated
  env_vars              = each.value.env_vars
  secrets               = each.value.secrets
  max_instances         = each.value.max_instances
  min_instances         = each.value.min_instances
  memory                = each.value.memory
  # Only api-core talks to Postgres; games/spa-origin never mount the socket.
  cloud_sql_instances = each.key == "api-core" && var.enable_cloud_sql ? [module.cloud_sql[0].connection_name] : []
  labels              = merge(local.base_labels, { service = each.key })
}

# HTTPS edge: global IP, managed certs, URL-map host routing, Cloud CDN bucket.
module "edge_lb" {
  source = "./modules/edge_lb"

  project     = var.project_id
  name_prefix = "cv-edge"

  # One managed cert per routed host (hostname is both label and FQDN).
  domains = {
    for host in keys(var.host_routing) : host => host
  }

  backends = local.neg_backends

  # Prefix-route the SPA's static assets to the Cloud CDN bucket.
  path_routes = local.cdn_path_route

  labels = merge(local.base_labels, { service = "edge-lb" })
}

# Cloud Armor: DDoS/abuse protection for CDN static assets
module "cloud_armor" {
  count  = var.enable_cloud_armor ? 1 : 0
  source = "./modules/cloud_armor"

  project     = var.project_id
  name_prefix = "cv-edge"

  rate_limit_count        = var.cloud_armor_rate_limit_count
  rate_limit_interval_sec = var.cloud_armor_rate_limit_interval_sec
  attach_to_proxy         = false # Static policy only; proxy attachment handled separately if needed
}

# GCS origin for Cloud CDN static assets (created when static_assets.enabled).
module "static_bucket" {
  source       = "./modules/static_bucket"
  count        = var.static_assets != null && var.static_assets.enabled ? 1 : 0
  name         = var.static_assets.bucket_name
  project      = var.project_id
  location     = var.static_assets.location
  cors_origins = var.static_assets.cors_origins
  labels       = merge(local.base_labels, { service = "static-bucket" })
}

# Private upload bucket for user content (avatars/photos) — deny-public, no CDN,
# writes only via server-generated signed URLs.
# NOTE: kept commented OUT deliberately — the operator is practicing tf plan/apply
# cycles with the CDN static bucket first. Uncomment (and set the `uploads` var)
# when ready to provision it.
module "uploads" {
  source = "./modules/uploads"
  count  = var.uploads != null ? 1 : 0

  name           = var.uploads.bucket_name
  project        = var.project_id
  location       = var.uploads.location
  app_sa         = var.uploads.app_sa
  write_prefixes = var.uploads.write_prefixes
  labels         = merge(local.base_labels, { service = "uploads" })
}

# DNS records for apex + subdomains -> the LB IP.
module "dns" {
  source = "./modules/dns"

  project            = var.project_id
  apex_domain        = var.apex_domain
  dns_name           = local.dns_name
  load_balancer_ipv4 = module.edge_lb.ipv4_address
  subdomains         = var.subdomains
  create_zone        = var.create_dns_zone
  labels             = merge(local.base_labels, { service = "dns" })
}
