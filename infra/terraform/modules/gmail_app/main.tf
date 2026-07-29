# =============================================================================
# Gmail API OAuth application (Gap 3) - PLACEHOLDER MODULE
# =============================================================================
#
# IMPORTANT: A real Gmail OAuth application CANNOT be created via Terraform /
# the Google Cloud provider. The OAuth consent screen, OAuth client credentials,
# Gmail API scopes and the Pub/Sub watch must be created manually in the Google
# Cloud Console. This module therefore records the intended configuration and
# outputs the values the application needs, so that the manual setup can be
# verified against a single source of truth.
#
# What MUST be done manually (see docs/GMAIL_SETUP.md):
#   MANUAL STEP 1: Enable the Gmail API and Pub/Sub API in the GCP project.
#   MANUAL STEP 2: Configure the OAuth consent screen (production/published).
#   MANUAL STEP 3: Create an OAuth 2.0 client (web application) with the
#                  redirect URI below.
#   MANUAL STEP 4: Grant scopes gmail.readonly (read pilot) and gmail.send
#                  (live send, separate re-authorization). See docs/GMAIL_SETUP.md
#                  "Permission separation".
#   MANUAL STEP 5: Create the Pub/Sub topic and push subscription; allow the
#                  Gmail service to publish to the topic.
#   MANUAL STEP 6: Seed the OAuth client secret into Secret Manager
#                  (gmail_client_secret) - referenced below.
#   MANUAL STEP 7: Record the client id and pubsub verification token as
#                  environment variables (WORKBUDDY_GMAIL_CLIENT_ID,
#                  WORKBUDDY_GMAIL_TOPIC_NAME, WORKBUDDY_GMAIL_PUBSUB_VERIFICATION_TOKEN).
#
# Acceptance: token revocation test and historyId expiry recovery drill must
# pass before Gate D (see docs/GMAIL_SETUP.md "Acceptance cases").
# =============================================================================

# This data/null resource documents the required Gmail configuration. It creates
# nothing in GCP but keeps the intended values in state for verification.
resource "null_resource" "gmail_app_config" {
  triggers = {
    redirect_uri           = var.redirect_uri
    pubsub_topic_name      = var.pubsub_topic_name
    client_secret_ref      = var.gmail_client_secret_id
    readonly_scope         = "https://www.googleapis.com/auth/gmail.readonly"
    send_scope             = "https://www.googleapis.com/auth/gmail.send"
    manual_setup_required  = "true"
  }
}
