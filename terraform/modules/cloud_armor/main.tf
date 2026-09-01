# Cloud Armor security policy for DDoS/abuse protection on CDN static assets.
# Rate-limits traffic to prevent abuse and scraping of static assets.

resource "google_compute_security_policy" "cdn_protection" {
  name        = "${var.name_prefix}-cdn-policy"
  description = "Cloud Armor protection for ${var.name_prefix} CDN static assets"
  project     = var.project

  # Rate limiting: max configured requests per IP per interval
  rule {
    action   = "rate-based-ban"
    priority = "100"
    match {
      expr {
        expression = "origin.region_code == 'US' || origin.region_code == 'EU'"
      }
    }
    rate_limit_options {
      conform_action   = "allow"
      exceed_action    = "deny-429"
      enforce_on_key   = "IP"
      ban_duration_sec = 600

      rate_limit_threshold {
        count        = var.rate_limit_count
        interval_sec = var.rate_limit_interval_sec
      }
    }
    description = "Rate limit: ${var.rate_limit_count} requests per ${var.rate_limit_interval_sec}s per IP"
  }

  # Allow normal traffic
  rule {
    action   = "allow"
    priority = "1000"
    match {
      expr {
        expression = "true"
      }
    }
    description = "Allow all other traffic"
  }
}
