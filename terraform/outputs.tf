output "load_balancer_ipv4" {
  description = "Global LB IPv4 address (all subdomain A records point here)."
  value       = module.edge_lb.ipv4_address
}

output "service_urls" {
  description = "Map of workloads -> deployed Cloud Run service names."
  value       = { for k, v in module.run : k => v.service_name }
}

output "neg_names" {
  description = "Map of workloads -> serverless NEG names."
  value       = { for k, v in module.run : k => v.neg_id }
}

output "nameservers" {
  description = "DNS nameservers to register at the registrar when create_dns_zone=true."
  value       = module.dns.nameservers
}

output "checksum" {
  description = "Quick sanity marker (terraform apply succeeded)."
  value       = "phase1a-edge-ready"
}

output "static_bucket" {
  description = "Cloud CDN static-asset bucket name (empty when disabled)."
  value       = var.static_assets != null && var.static_assets.enabled ? module.static_bucket[0].bucket_name : ""
}

output "uploads_bucket" {
  description = "Private user-content bucket name (empty when disabled). Signed-URL only."
  value       = "unprovisioned" # requires the uploads module (currently commented out)
}

