resource "google_cloud_run_v2_service" "service" {
  name     = var.name
  location = var.region
  project  = var.project
  labels   = var.labels

  ingress = var.ingress

  template {
    execution_environment = var.execution_environment
    timeout               = "${var.timeout_seconds}s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      dynamic "env" {
        for_each = var.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = env.value.version
            }
          }
        }
      }

      resources {
        cpu_idle          = var.min_instances == 0 ? true : false
        startup_cpu_boost = true
        limits = {
          cpu    = tostring(var.cpu)
          memory = var.memory
        }
      }

      dynamic "volume_mounts" {
        for_each = length(var.cloud_sql_instances) > 0 ? [1] : []
        content {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }

    dynamic "volumes" {
      for_each = length(var.cloud_sql_instances) > 0 ? [1] : []
      content {
        name = "cloudsql"
        cloud_sql_instance {
          instances = var.cloud_sql_instances
        }
      }
    }

    service_account = var.service_account_email
  }

  # Terraform owns the service's shape (scaling, secrets, env vars); the
  # deploy-app.yml pipeline owns which image tag is live via `gcloud run
  # deploy`. Without this, each tool reverts the other's most recent change.
  #
  # Autoscaling is configured in template.scaling above. The SERVICE-level
  # `scaling` block is a separate Cloud Run v2 field (manual instance pinning)
  # that this module never sets; the API still returns zeros for it, which
  # Terraform reads as a removable block and re-plans on every run. Ignoring it
  # keeps `terraform plan` clean in CI instead of showing a diff that never
  # converges.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, scaling]
  }
}

# Invoker binding. Requests arriving through the load balancer are still
# unauthenticated as far as Cloud Run is concerned, so a public-facing service
# needs allUsers/run.invoker even though `ingress` already restricts the
# traffic source to the LB. Without this the edge returns 403.
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project
  location = google_cloud_run_v2_service.service.location
  name     = google_cloud_run_v2_service.service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Serverless NEG so the Load Balancer can route to this service. The NEG
# authenticates to Cloud Run with default service identity and the URL-map
# host rule targets it; direct public access is governed by `ingress`.
resource "google_compute_region_network_endpoint_group" "neg" {
  name                  = "${var.name}-neg"
  project               = var.project
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.service.name
  }
}
