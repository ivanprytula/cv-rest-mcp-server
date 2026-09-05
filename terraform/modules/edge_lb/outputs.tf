output "ipv4_address" {
  description = "Global LB IPv4 address; point all subdomain A records here (DNS module does this automatically)."
  value       = google_compute_global_address.default.address
}

output "url_map_name" {
  description = "URL map name."
  value       = google_compute_url_map.edge.name
}

output "certificates" {
  description = "Map of host label -> managed cert self link."
  value       = { for k, v in google_compute_managed_ssl_certificate.edge : k => v.id }
  sensitive   = true
}

output "https_proxy_name" {
  description = "HTTPS target proxy name."
  value       = google_compute_target_https_proxy.edge.name
}
