# GitHub Workload Identity Federation (WIF) for CI/CD.
# Enables GitHub Actions to authenticate to GCP without storing service account keys.
# One-time setup: creates the pool, OIDC provider, and IAM bindings.

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  project                   = var.project
  display_name              = "GitHub Actions"
  description               = "Workload Identity Pool for GitHub Actions CI/CD"
  disabled                  = false
}

# GitHub OIDC provider: repository-scoped trust via attribute condition.
# attribute_condition checks the mapped attribute.repository against the configured repo.
resource "google_iam_workload_identity_pool_provider" "github_oidc" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "gh-actions"
  project                            = var.project
  display_name                       = "GitHub Actions OIDC"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.aud"        = "assertion.aud"
  }
  # Condition: only trust tokens from the configured repository
  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# IAM binding: allow GitHub principal to impersonate the deployer SA
resource "google_service_account_iam_member" "github_deployer" {
  service_account_id = "projects/${var.project}/serviceAccounts/${var.deployer_sa_email}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
