# =============================================================================
# GCP Workload Identity Federation for GitHub Actions (Gap 3)
# =============================================================================
#
# Lets GitHub Actions authenticate to GCP using short-lived OIDC tokens issued by
# GitHub - no long-lived service-account JSON keys are stored in GitHub secrets.
#
# Components:
#   * A Workload Identity Pool
#   * A Workload Identity Pool Provider that trusts GitHub's OIDC issuer
#     (https://token.actions.githubusercontent.com) and is constrained to a
#     specific repository via attribute condition / mapping
#   * A GCP service account that GitHub Actions impersonates
#   * IAM binding granting the pool principal tokenExchange on the service account
#
# In the CI workflow (see .github/workflows/ci.yml), the `google-github-actions/
# auth` action uses `workload_identity_provider` and `service_account` to mint a
# short-lived GCP credential. This closes the "stored secrets" anti-pattern.
# =============================================================================

# Workload Identity Pool for GitHub Actions.
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions"
  description               = "OIDC federation pool for GitHub Actions deployments."
  disabled                  = false
}

# Workload Identity Pool Provider trusting GitHub's OIDC issuer.
resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = "GitHub OIDC"
  description                        = "Trusts token.actions.githubusercontent.com for ${var.github_repo}."

  # GitHub's OIDC issuer.
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  # Map GitHub OIDC claims to GCP attribute conditions.
  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
    "attribute.event_name"       = "assertion.event_name"
  }

  # Restrict impersonation to the configured repository (and, optionally, the
  # main branch for production deploys). This is the key security boundary.
  attribute_condition = "assertion.repository == \"${var.github_repo}\""

  depends_on = [google_iam_workload_identity_pool.github]
}

# Service account GitHub Actions impersonates for terraform plan/apply.
resource "google_service_account" "github_actions" {
  project      = var.project_id
  account_id   = var.github_actions_service_account
  display_name = "GitHub Actions deployer"
  description  = "Impersonated by GitHub Actions via Workload Identity Federation."
}

# Allow the Workload Identity Pool principal to impersonate the service account.
# The principal set is scoped to the pool (and further constrained by the
# provider attribute_condition to the specific repository).
resource "google_service_account_iam_member" "workload_identity_user" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
