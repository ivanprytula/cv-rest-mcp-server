locals {
  # Resolve each logical backend to the resource Terraform manages it with:
  # serverless NEGs back serverless backend services; static buckets become
  # Cloud CDN-enabled backend buckets.
  backend_refs = {
    for k, v in var.backends :
    k => (
      v.type == "bucket"
      ? google_compute_backend_bucket.bucket[k].id
      : google_compute_backend_service.neg[k].id
    )
  }
  default_backend = values(local.backend_refs)[0]

}

# Global anycast IPv4 that all subdomains resolve to.
resource "google_compute_global_address" "default" {
  name    = "${var.name_prefix}-ipv4"
  project = var.project
}

# Serverless backend services (one per host routed to a Cloud Run NEG).
resource "google_compute_backend_service" "neg" {
  for_each              = { for k, v in var.backends : k => v if v.type == "neg" }
  name                  = "${var.name_prefix}-bs-${lower(replace(each.key, ".", "-"))}"
  project               = var.project
  protocol              = "HTTP"
  port_name             = "http"
  timeout_sec           = 30
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = each.value.neg_self_link
  }
}

# Cloud CDN-backed static buckets (SPA assets).
resource "google_compute_backend_bucket" "bucket" {
  for_each    = { for k, v in var.backends : k => v if v.type == "bucket" }
  name        = "${var.name_prefix}-bb-${lower(replace(each.key, ".", "-"))}"
  project     = var.project
  bucket_name = each.value.bucket
  enable_cdn  = var.enable_cdn
  cdn_policy {
    cache_mode = "CACHE_ALL_STATIC"
  }
}

# Prefix-routed CDN buckets for static assets (e.g. app/<apex>/assets/*).
resource "google_compute_backend_bucket" "path_bucket" {
  for_each    = var.path_routes
  name        = "${var.name_prefix}-bb-${lower(replace(each.key, ".", "-"))}"
  project     = var.project
  bucket_name = each.value.bucket
  enable_cdn  = var.enable_cdn
  cdn_policy {
    cache_mode = "CACHE_ALL_STATIC"
  }
}

# Google-managed SSL certificates, one per host label.
resource "google_compute_managed_ssl_certificate" "edge" {
  for_each = var.domains
  # Strip domain suffix so only the first label remains (dots not allowed in cert name).
  name    = "${var.name_prefix}-cert-${lower(replace(each.key, ".", "-"))}"
  project = var.project
  managed {
    domains = [each.value]
  }
}

# Host routing: each fully-qualified hostname maps to its backend.
resource "google_compute_url_map" "edge" {
  name            = "${var.name_prefix}-url-map"
  project         = var.project
  default_service = local.default_backend

  lifecycle {
    precondition {
      condition     = alltrue([for h in keys(var.path_routes) : contains(keys(var.backends), h)])
      error_message = "Every path_routes host (${join(", ", keys(var.path_routes))}) must also exist as a key in backends."
    }
  }

  dynamic "host_rule" {
    for_each = var.backends
    content {
      hosts        = [host_rule.key]
      path_matcher = "m-${lower(replace(host_rule.key, ".", "-"))}"
    }
  }

  dynamic "path_matcher" {
    for_each = var.backends
    content {
      name            = "m-${lower(replace(path_matcher.key, ".", "-"))}"
      default_service = local.backend_refs[path_matcher.key]

      # For hosts with a path_route entry, the matched prefix (e.g. /assets/*)
      # is served from the CDN bucket; everything else falls through to the
      # host's default (the container NEG).
      dynamic "path_rule" {
        for_each = contains(keys(var.path_routes), path_matcher.key) ? [1] : []
        content {
          paths   = [var.path_routes[path_matcher.key].prefix]
          service = google_compute_backend_bucket.path_bucket[path_matcher.key].id
        }
      }
    }
  }
}

resource "google_compute_target_https_proxy" "edge" {
  name             = "${var.name_prefix}-https-proxy"
  project          = var.project
  url_map          = google_compute_url_map.edge.id
  ssl_certificates = [for c in google_compute_managed_ssl_certificate.edge : c.id]
}

resource "google_compute_global_forwarding_rule" "https" {
  name                  = "${var.name_prefix}-https-fwd"
  project               = var.project
  target                = google_compute_target_https_proxy.edge.id
  ip_address            = google_compute_global_address.default.address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
