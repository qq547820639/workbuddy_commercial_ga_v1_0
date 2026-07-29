output "app_secret_secret_id" {
  description = "Secret Manager id of app_secret."
  value       = google_secret_manager_secret.app_secret.id
}

output "token_encryption_key_secret_id" {
  description = "Secret Manager id of token_encryption_key."
  value       = google_secret_manager_secret.token_encryption_key.id
}

output "db_password_secret_id" {
  description = "Secret Manager id of db_password."
  value       = google_secret_manager_secret.db_password.id
}

output "gmail_client_secret_secret_id" {
  description = "Secret Manager id of gmail_client_secret."
  value       = google_secret_manager_secret.gmail_client_secret.id
}

output "graph_client_secret_secret_id" {
  description = "Secret Manager id of graph_client_secret."
  value       = google_secret_manager_secret.graph_client_secret.id
}

output "stripe_api_key_secret_id" {
  description = "Secret Manager id of stripe_api_key."
  value       = google_secret_manager_secret.stripe_api_key.id
}

output "billing_webhook_secret_secret_id" {
  description = "Secret Manager id of billing_webhook_secret."
  value       = google_secret_manager_secret.billing_webhook_secret.id
}

output "secret_ids" {
  description = "Map of logical secret name to Secret Manager resource id."
  value = {
    app_secret            = google_secret_manager_secret.app_secret.id
    token_encryption_key  = google_secret_manager_secret.token_encryption_key.id
    db_password           = google_secret_manager_secret.db_password.id
    gmail_client_secret   = google_secret_manager_secret.gmail_client_secret.id
    graph_client_secret   = google_secret_manager_secret.graph_client_secret.id
    stripe_api_key        = google_secret_manager_secret.stripe_api_key.id
    billing_webhook_secret = google_secret_manager_secret.billing_webhook_secret.id
  }
}
