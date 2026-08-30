resource "google_dns_managed_zone" "zone" {
  count       = var.create_zone ? 1 : 0
  project     = var.project
  name        = replace(trimsuffix(var.dns_name, "."), ".", "-")
  dns_name    = var.dns_name
  description = "Public zone for the Phase 1a multi-subdomain edge (${var.apex_domain})."
  dnssec_config {
    state         = "on"
    non_existence = "nsec3"
  }
}

# Every subdomain (plus the apex) resolves to the single global LB IPv4.
resource "google_dns_record_set" "subdomain" {
  count        = var.create_zone ? length(var.subdomains) : 0
  project      = var.project
  managed_zone = google_dns_managed_zone.zone[0].name
  name         = var.subdomains[count.index] == "@" ? var.dns_name : "${var.subdomains[count.index]}.${var.dns_name}"
  type         = "A"
  ttl          = var.ttl
  rrdatas      = [var.load_balancer_ipv4]
}
