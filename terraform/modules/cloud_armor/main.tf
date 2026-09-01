# Cloud Armor security policy for DDoS/abuse protection on CDN static assets.
# Rate-limits traffic to prevent abuse and scraping of static assets.

resource "google_compute_security_policy" "cdn_protection" {
  name        = "${var.name_prefix}-cdn-policy"
  description = "Cloud Armor protection for ${var.name_prefix} CDN static assets"
  project     = var.project

  # Rate limiting: max configured requests per IP per interval (all traffic)
  rule {
    action   = "rate_based_ban"
    priority = "100"
    match {
      expr {
        expression = "true"
      }
    }
    rate_limit_options {
      conform_action   = "allow"
      exceed_action    = "deny(429)"
      enforce_on_key   = "IP"
      ban_duration_sec = 600

      rate_limit_threshold {
        count        = var.rate_limit_count
        interval_sec = var.rate_limit_interval_sec
      }
    }
    description = "Rate limit: ${var.rate_limit_count} requests per ${var.rate_limit_interval_sec}s per IP"
  }

  # Default rule (required): allow all other traffic
  rule {
    action   = "allow"
    priority = "2147483647"
    match {
      expr {
        expression = "true"
      }
    }
    description = "Default allow rule"
  }
}
