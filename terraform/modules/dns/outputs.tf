output "zone_name" {
  description = "Managed zone name when create_zone=true, else empty."
  value       = var.create_zone ? google_dns_managed_zone.zone[0].name : ""
}

output "nameservers" {
  description = "Authoritative nameservers to register at the registrar (NS delegation) when create_zone=true."
  value       = var.create_zone ? google_dns_managed_zone.zone[0].name_servers : []
}
