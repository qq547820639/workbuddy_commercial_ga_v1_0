output "redirect_uri" {
  description = "Configured Gmail OAuth redirect URI (must match the Console)."
  value       = var.redirect_uri
}

output "pubsub_topic_name" {
  description = "Configured Pub/Sub topic name for Gmail notifications."
  value       = var.pubsub_topic_name
}

output "gmail_client_secret_ref" {
  description = "Secret Manager resource id holding the Gmail client secret."
  value       = var.gmail_client_secret_id
}

output "required_scopes" {
  description = "Gmail OAuth scopes to grant (readonly + send, separately authorized)."
  value = {
    readonly = "https://www.googleapis.com/auth/gmail.readonly"
    send     = "https://www.googleapis.com/auth/gmail.send"
  }
}

output "manual_setup_required" {
  description = "Always true - the Gmail OAuth app must be created in the Google Cloud Console."
  value       = true
}
