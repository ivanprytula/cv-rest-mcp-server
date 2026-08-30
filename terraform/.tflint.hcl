# TFLint configuration for the Phase 1a Terraform edge.
# Run as part of pre-commit (terraform_tflint) and `just tf-lint`.
# Only the built-in `terraform` ruleset is enabled so the hook is fully
# self-contained (no `tflint --init` network step). Add the google plugin only
# if you accept running `tflint --init` to fetch it.
plugin "terraform" {
  enabled = true
}

rule "terraform_unused_declarations" {
  enabled = true
}

rule "terraform_comment_syntax" {
  enabled = true
}
