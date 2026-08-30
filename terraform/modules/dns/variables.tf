variable "project" {
  description = "Google Cloud project ID."
  type        = string
}

variable "apex_domain" {
  description = "Apex domain without wildcards, e.g. example.com."
  type        = string
}

variable "dns_name" {
  description = "Managed zone DNS name, e.g. example.com. (normally apex_domain + '.')."
  type        = string
}

variable "load_balancer_ipv4" {
  description = "Global LB IPv4 address that every subdomain A record points to."
  type        = string
}

variable "subdomains" {
  description = "Hostnames to create as A records -> load_balancer_ipv4. Include apex ('' or '@') plus www/api/app/games. Entries are bare hostnames, e.g. 'api'; use '@' for the apex."
  type        = list(string)
  default     = ["@", "www", "api", "app", "games"]
}

variable "create_zone" {
  description = "Create the managed zone. False = records skipped but NS/zone not owned here (DNS stays at the current provider)."
  type        = bool
  default     = true
}

variable "ttl" {
  description = "DNS record TTL in seconds."
  type        = number
  default     = 300
}
