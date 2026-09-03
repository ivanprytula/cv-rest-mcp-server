# Cloud SQL Postgres instance for the auth/user store (ADR-023 Phase 2).
# Postgres 17, db-f1-micro, zonal, no HA — cheapest viable tier; confirmed via
# Infracost at ~$9/month, well under the $100/month ceiling. Connected to
# from Cloud Run via the Cloud SQL Auth Proxy's native socket mount
# (modules/cloud_run_service), not a Serverless VPC Access connector.

resource "google_sql_database_instance" "instance" {
  name             = var.instance_name
  project          = var.project
  region           = var.region
  database_version = "POSTGRES_17"

  settings {
    tier              = var.tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_autoresize   = true
    disk_size         = var.disk_size_gb
    user_labels       = var.labels

    # GCP API-level delete guard — separate from the resource-level
    # deletion_protection below, which only blocks `terraform destroy`.
    # This one blocks the delete button/API call itself, from any tool.
    deletion_protection_enabled = var.deletion_protection

    backup_configuration {
      enabled = var.backups_enabled
    }

    # Cloud SQL requires at least one of public IP / private IP / PSC
    # enabled — there's no VPC peering or PSC config in this project (that's
    # the whole point of using the Auth Proxy over a VPC connector), so
    # public IP is the only option here. The Cloud Run Auth Proxy socket
    # mount (modules/cloud_run_service) still authenticates via the Cloud
    # SQL Admin API + mutual TLS rather than a raw open port; no inbound
    # rule exposes 5432 to the open internet. ssl_mode enforces encryption
    # on any connection regardless of transport.
    ip_configuration {
      ipv4_enabled = true
      # ssl_mode superseded require_ssl in provider hashicorp/google ~> 6.0;
      # ENCRYPTED_ONLY is the current equivalent of require_ssl = true.
      ssl_mode = "ENCRYPTED_ONLY"
    }

    database_flags {
      name  = "log_lock_waits"
      value = "on"
    }
    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }
    database_flags {
      name  = "log_connections"
      value = "on"
    }
    database_flags {
      name  = "log_disconnections"
      value = "on"
    }
    database_flags {
      name  = "log_hostname"
      value = "on"
    }
    database_flags {
      name  = "log_duration"
      value = "on"
    }
    database_flags {
      name  = "cloudsql.enable_pgaudit"
      value = "on"
    }
    database_flags {
      name  = "log_statement"
      value = "all"
    }
    database_flags {
      name  = "log_min_messages"
      value = "error"
    }
  }

  # PR6 (14-day fallback window) explicitly requires this instance to survive
  # an accidental `terraform destroy` while the file-fallback path is still
  # the safety net; the pre-existing data must not vanish before it does.
  deletion_protection = var.deletion_protection
}

resource "google_sql_database" "app" {
  name     = var.database_name
  project  = var.project
  instance = google_sql_database_instance.instance.name
}

# Password value/version is script-owned (scripts/deploy-cloud-run.sh
# bootstrap_secrets(), following the same convention as
# cv-jwt-signing-key/cv-refresh-token-pepper) — never entering .tfvars or
# Terraform state. This data source only reads the latest version to hand to
# google_sql_user below.
data "google_secret_manager_secret_version" "db_password" {
  secret  = var.db_password_secret_id
  project = var.project
}

resource "google_sql_user" "app" {
  name     = var.database_user
  project  = var.project
  instance = google_sql_database_instance.instance.name
  password = data.google_secret_manager_secret_version.db_password.secret_data
}
