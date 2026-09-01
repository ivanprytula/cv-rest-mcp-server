# Organization Policies for security guardrails
# Defense-in-depth: runtime enforcement of bucket policies that code validation
# cannot express (ensure_deny_public.py is the static-analysis guard).

# Enforce uniform bucket-level access and public access prevention
resource "google_org_policy_policy" "uniform_bucket_level_access" {
  name   = "projects/${var.project}/policies/storage.uniformBucketLevelAccess"
  parent = "projects/${var.project}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }
}

# Deny public access to storage buckets (except where signed URLs are used)
resource "google_org_policy_policy" "deny_bucket_public_access" {
  name   = "projects/${var.project}/policies/storage.publicAccessPrevention"
  parent = "projects/${var.project}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }
}
