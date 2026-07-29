# =============================================================================
# Microsoft Entra ID application registration (Gap 3)
# =============================================================================
#
# Registers the WorkBuddy production application in Microsoft Entra ID with:
#   * Mail.Read.Shared (delegated) - read shared mailbox content
#   * Mail.Send (delegated)        - send mail, separately authorized
#
# Per docs/MICROSOFT_GRAPH_SETUP.md, read and send must be separately authorized
# and staging/production use different Entra application registrations.
#
# The generated client secret is written to GCP Secret Manager
# (graph_client_secret) so no Entra credential is checked into Git/ConfigMap.
#
# MANUAL STEP: after apply, an Entra admin must grant admin consent for the
# Mail.Read.Shared and Mail.Send delegated permissions. Graph webhook
# subscription renewal and clientState are handled by the application runtime.
# =============================================================================

# Microsoft Entra application registration.
resource "azuread_application" "workbuddy" {
  display_name = var.display_name
  owners       = var.owner_object_ids

  # Web redirect URI for the OAuth authorization code flow. Matches
  # WORKBUDDY_GRAPH_REDIRECT_URI in docs/MICROSOFT_GRAPH_SETUP.md.
  web {
    redirect_uris = [var.graph_redirect_uri]
  }

  # Microsoft Graph delegated permissions.
  # Resource app id 00000003-0000-0000-c000-000000000000 = Microsoft Graph.
  #   * Mail.Read.Shared (delegated): 2a8d57a5-d7c4-4d3b-bf3e-2e081f3c6f95
  #   * Mail.Send        (delegated): e383f46e-2787-4521-874e-ec2ae3b9cf61
  # Verify the permission GUIDs against the Microsoft Graph permissions reference
  # before applying: https://learn.microsoft.com/graph/permissions-reference
  required_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000"

    resource_access {
      id   = "2a8d57a5-d7c4-4d3b-bf3e-2e081f3c6f95" # Mail.Read.Shared
      type = "Scope"
    }

    resource_access {
      id   = "e383f46e-2787-4521-874e-ec2ae3b9cf61" # Mail.Send
      type = "Scope"
    }
  }
}

# Service principal for the application so it can be granted consent and used
# by the runtime to request tokens.
resource "azuread_service_principal" "workbuddy" {
  application_id = azuread_application.workbuddy.application_id
  owners         = var.owner_object_ids

  # Tags help locate the app in the Entra admin center.
  use_in_default_app_role_assignment_for_shared = false

  feature_tags {
    enterprise = true
    gallery    = false
  }
}

# Client secret for the application. The plaintext is stored only in GCP Secret
# Manager; this resource exposes the value once so it can be written to Secret
# Manager, and is marked sensitive.
resource "azuread_application_password" "workbuddy" {
  application_object_id = azuread_application.workbuddy.object_id
  display_name          = "workbuddy-production-graph-secret"
  end_date_relative     = "17520h" # ~2 years; rotate before expiry
}

# Store the Entra client secret in GCP Secret Manager so the WorkBuddy runtime
# reads WORKBUDDY_GRAPH_CLIENT_SECRET from Secret Manager, never from Git.
resource "google_secret_manager_secret_version" "graph_client_secret" {
  secret      = var.graph_client_secret_id
  secret_data = azuread_application_password.workbuddy.value
}
