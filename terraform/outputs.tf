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

output "deployer_sa_email" {
  description = "CI/CD deployer service account email (use in GitHub WIF_DEPLOY_SA secret)."
  value       = module.iam_secrets.deployer_sa_email
}

output "cv_images_repo_url" {
  description = "Artifact Registry docker repo path for app images (used by deploy-app.yml)."
  value       = module.iam_secrets.cv_images_repo_url
}

output "github_wif_provider" {
  description = "GitHub WIF provider URI (use in GitHub WIF_PROVIDER secret, only when setup_github_wif=true)."
  value       = var.setup_github_wif ? module.github_wif[0].workload_identity_provider : ""
  sensitive   = true
}

output "org_policies_enforced" {
  description = "Organization Policies enforced (uniform bucket access, deny-public)."
  value       = var.setup_org_policies ? "true" : "false"
}

output "cloud_armor_policy_id" {
  description = "Cloud Armor security policy ID for CDN DDoS protection (if enabled)."
  value       = var.enable_cloud_armor ? module.cloud_armor[0].security_policy_id : ""
}

output "cloud_armor_rate_limit" {
  description = "Cloud Armor rate limit config (requests per interval)."
  value       = var.enable_cloud_armor ? "${var.cloud_armor_rate_limit_count}/${var.cloud_armor_rate_limit_interval_sec}s" : "disabled"
}

