variable "project" {
  description = "Google Cloud project ID."
  type        = string
}

variable "name_prefix" {
  description = "Prefix for all edge resource names."
  type        = string
  default     = "cv-edge"
}

variable "domains" {
  description = "Map of host label -> fully-qualified domain for Google-managed SSL certs, e.g. { api = \"api.example.com\" }."
  type        = map(string)
}

variable "backends" {
  description = <<-EOT
    Map of hostname -> backend definition. Each hostname becomes a URL-map host rule.
      neg_host = {
        type           = "neg"
        neg_self_link  = "<serverless NEG self link>"
        neg_region     = "<region of the NEG>"
      }
      static_host = {
        type       = "bucket"
        bucket     = "gs://<bucket>"   # CDN-backed static bucket (no neg_* keys)
      }
  EOT
  type = map(object({
    type          = string
    neg_self_link = optional(string)
    neg_region    = optional(string)
    bucket        = optional(string)
  }))
}

variable "enable_cdn" {
  description = "Enable Cloud CDN on the static (bucket) backends."
  type        = bool
  default     = true
}

variable "path_routes" {
  description = <<-EOT
    Prefix-routed static backends WITHIN an existing host (e.g. app/<apex>/assets/*
    -> CDN bucket while app/<apex> stays on the container). Key = the FQDN host
    that must already exist in `backends`; each entry adds a URL-map path rule
    for the given prefix pointing at a Cloud CDN backend bucket.
        "app.example.com" = {
          prefix = "/assets/"
          bucket = "cv-example-static"   # GCS bucket name (see modules/static_bucket)
        }
  EOT
  type = map(object({
    prefix = string
    bucket = string
  }))
  default = {}
}

variable "labels" {
  description = "GCP resource labels for cost attribution (e.g. { service = \"edge-lb\", environment = \"production\" })."
  type        = map(string)
  default     = {}
}
