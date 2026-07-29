# =============================================================================
# Google Secret Manager - application credential containers (Gap 3 / Gap 4)
# =============================================================================
#
# Creates the Secret Manager *containers* (google_secret_manager_secret) for every
# credential WorkBuddy requires in production. See docs/IDENTITY_AND_ACCESS.md:
# token encryption key must be separate from the app secret, OAuth tokens are
# stored only encrypted, and model/OAuth/db/object-store keys live in Secret
# Manager - never in ConfigMap, Git, logs or frontend responses.
#
# This module creates the secret resources only. Secret *values* are seeded out
# of band, except:
#   * db_password        - written by the root module (random_password)
#   * graph_client_secret - written by the entra_app module (generated client secret)
#
# MANUAL STEP: seed the remaining secret values after the first apply:
#   echo -n "VALUE" | gcloud secrets versions add app_secret --data-file=-
#   echo -n "VALUE" | gcloud secrets versions add token_encryption_key --data-file=-
#   echo -n "VALUE" | gcloud secrets versions add gmail_client_secret --data-file=-
#   echo -n "VALUE" | gcloud secrets versions add stripe_api_key --data-file=-
#   echo -n "VALUE" | gcloud secrets versions add billing_webhook_secret --data-file=-
# Restrict IAM access to the runtime service account and platform team only.
# =============================================================================

# Application secret (HMAC/session signing). Must be >= 32 chars (see preflight).
resource "google_secret_manager_secret" "app_secret" {
  project   = var.project_id
  secret_id = "app_secret"
  replication {
    auto {}
  }
  labels = var.labels
}

# Fernet token encryption key used to encrypt stored OAuth refresh tokens.
# MUST be separate from app_secret per docs/IDENTITY_AND_ACCESS.md.
resource "google_secret_manager_secret" "token_encryption_key" {
  project   = var.project_id
  secret_id = "token_encryption_key"
  replication {
    auto {}
  }
  labels = var.labels
}

# Cloud SQL application password. Value written by the root module.
resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = "db_password"
  replication {
    auto {}
  }
  labels = var.labels
}

# Gmail OAuth client secret. MANUAL STEP: create the OAuth client in Google
# Cloud Console (see docs/GMAIL_SETUP.md) and seed the value here.
resource "google_secret_manager_secret" "gmail_client_secret" {
  project   = var.project_id
  secret_id = "gmail_client_secret"
  replication {
    auto {}
  }
  labels = var.labels
}

# Microsoft Graph / Entra application client secret. Value written by the
# entra_app module.
resource "google_secret_manager_secret" "graph_client_secret" {
  project   = var.project_id
  secret_id = "graph_client_secret"
  replication {
    auto {}
  }
  labels = var.labels
}

# Stripe API key for the billing provider. MANUAL STEP: obtain from Stripe
# dashboard and seed after billing provider selection.
resource "google_secret_manager_secret" "stripe_api_key" {
  project   = var.project_id
  secret_id = "stripe_api_key"
  replication {
    auto {}
  }
  labels = var.labels
}

# Billing webhook signing secret. MANUAL STEP: set after the billing provider
# webhook endpoint is registered.
resource "google_secret_manager_secret" "billing_webhook_secret" {
  project   = var.project_id
  secret_id = "billing_webhook_secret"
  replication {
    auto {}
  }
  labels = var.labels
}
