provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
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
  image                 = each.value.image
  service_account_email = each.value.service_account
  allow_unauthenticated = each.value.allow_unauthenticated
  env_vars              = each.value.env_vars
  secrets               = each.value.secrets
  max_instances         = each.value.max_instances
  min_instances         = each.value.min_instances
  memory                = each.value.memory
}

# HTTPS edge: global IP, managed certs, URL-map host routing, Cloud CDN bucket.
module "edge_lb" {
  source = "./modules/edge_lb"

  project     = var.project_id
  name_prefix = "cv-edge"
  region      = var.region

  # One managed cert per routed host (hostname is both label and FQDN).
  domains = {
    for host in keys(var.host_routing) : host => host
  }

  backends = local.neg_backends

  # Prefix-route the SPA's static assets to the Cloud CDN bucket.
  path_routes = local.cdn_path_route
}

# GCS origin for Cloud CDN static assets (created when static_assets.enabled).
module "static_bucket" {
  source       = "./modules/static_bucket"
  count        = var.static_assets != null && var.static_assets.enabled ? 1 : 0
  name         = var.static_assets.bucket_name
  project      = var.project_id
  location     = var.static_assets.location
  cors_origins = var.static_assets.cors_origins
}

# Private upload bucket for user content (avatars/photos) — deny-public, no CDN,
# writes only via server-generated signed URLs.
# NOTE: kept commented OUT deliberately — the operator is practicing tf plan/apply
# cycles with the CDN static bucket first. Uncomment (and set the `uploads` var)
# when ready to provision it.
# module "uploads" {
#   source = "./modules/uploads"
#   count  = var.uploads != null ? 1 : 0
#
#   name            = var.uploads.bucket_name
#   project         = var.project_id
#   location        = var.uploads.location
#   app_sa          = var.uploads.app_sa
#   write_prefixes  = var.uploads.write_prefixes
# }

# DNS records for apex + subdomains -> the LB IP.
module "dns" {
  source = "./modules/dns"

  project            = var.project_id
  apex_domain        = var.apex_domain
  dns_name           = local.dns_name
  load_balancer_ipv4 = module.edge_lb.ipv4_address
  subdomains         = var.subdomains
  create_zone        = var.create_dns_zone
}
