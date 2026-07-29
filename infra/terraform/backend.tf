# Remote state backend.
#
# Terraform state for the WorkBuddy production infrastructure is stored in a
# dedicated, versioned GCS bucket. The bucket itself must be created out of band
# (bootstrap) before the first `terraform init`; it should have versioning,
# object locking and uniform bucket-level access enabled and be restricted to the
# platform team. See docs/CLOUD_SETUP_CHECKLIST.md.
#
# MANUAL STEP: create the state bucket once, e.g.
#   gcloud storage buckets create gs://workbuddy-tfstate-prod \
#     --project=YOUR_PROJECT_ID --location=asia-east2 \
#     --uniform-bucket-level-access
#   gcloud storage buckets update gs://workbuddy-tfstate-prod --versioning
# Then set backend.tfvars (or pass -backend-config) with the real bucket/prefix.

terraform {
  backend "gcs" {
    # Values are supplied via a backend config file (backend.tfvars) or
    # `-backend-config=` flags so that no real project identifiers are
    # committed to the repository.
    bucket = "workbuddy-tfstate-prod"
    prefix = "terraform/state"
  }
}
