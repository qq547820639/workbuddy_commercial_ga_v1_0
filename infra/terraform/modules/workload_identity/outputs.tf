output "pool_id" {
  description = "Fully qualified id of the Workload Identity Pool."
  value       = google_iam_workload_identity_pool.github.id
}

output "pool_name" {
  description = "Name of the Workload Identity Pool (iam.googleapis.com/...)."
  value       = google_iam_workload_identity_pool.github.name
}

output "provider_id" {
  description = "Fully qualified id of the Workload Identity Pool Provider."
  value       = google_iam_workload_identity_pool_provider.github.id
}

output "provider_name" {
  description = "Name of the Workload Identity Pool Provider used by the auth action."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "service_account_email" {
  description = "Email of the service account GitHub Actions impersonates."
  value       = google_service_account.github_actions.email
}

output "service_account_id" {
  description = "Unique id of the GitHub Actions service account."
  value       = google_service_account.github_actions.id
}
