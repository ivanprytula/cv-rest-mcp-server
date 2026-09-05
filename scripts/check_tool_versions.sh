#!/bin/bash
set -e

TF=$(grep terraform .tool-versions | cut -d' ' -f2)

if ! grep -q "terraform_version: \"$TF\"" .github/workflows/ci-cd.yml; then
  echo "⚠️  Terraform version mismatch:"
  echo "   .tool-versions: $TF"
  echo "   .github/workflows/ci-cd.yml: needs update"
  echo ""
  echo "   Run: sed -i 's/terraform_version: \"[0-9.]*\"/terraform_version: \"$TF\"/' .github/workflows/ci-cd.yml"
  exit 1
fi
