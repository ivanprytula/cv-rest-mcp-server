terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Remote state for this single managed environment (GCS). Bootstrap once with
  # `just deploy bootstrap-state` (creates the versioned bucket for you, then
  # runs init with the backend config below). The SAME versioned bucket provides
  # both state storage and locking — the GCS backend locks via an object
  # write-hold in the bucket, so there is no separate lock bucket. After the
  # bucket exists you may also pin it here directly, then `terraform init`:
  #
  backend "gcs" {
    bucket = "cv-rest-mcp-server-dev-tfstate"
    prefix = "terraform/state"
  }
}
