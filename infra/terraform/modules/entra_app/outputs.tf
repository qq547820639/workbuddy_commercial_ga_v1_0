output "client_id" {
  description = "Application (client) id of the Entra application registration. Maps to WORKBUDDY_GRAPH_CLIENT_ID."
  value       = azuread_application.workbuddy.application_id
}

output "object_id" {
  description = "Object id of the Entra application registration."
  value       = azuread_application.workbuddy.object_id
}

output "service_principal_id" {
  description = "Object id of the Entra service principal."
  value       = azuread_service_principal.workbuddy.object_id
}

output "service_principal_application_id" {
  description = "Application id of the Entra service principal."
  value       = azuread_service_principal.workbuddy.application_id
}

output "redirect_uri" {
  description = "Configured Graph OAuth redirect URI."
  value       = var.graph_redirect_uri
}

output "required_permissions" {
  description = "Microsoft Graph delegated permissions requested by the application."
  value = {
    mail_read_shared = "Mail.Read.Shared"
    mail_send        = "Mail.Send"
  }
}

output "graph_client_secret_ref" {
  description = "GCP Secret Manager resource id holding the Entra client secret."
  value       = var.graph_client_secret_id
  sensitive   = true
}
