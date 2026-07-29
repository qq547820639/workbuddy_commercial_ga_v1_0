# Root outputs exposing the most useful connection references for downstream
# Kubernetes configuration and operational runbooks. Secret values are never
# exposed here - only their Secret Manager resource identifiers.

output "project_id" {
  description = "GCP project hosting the production infrastructure."
  value       = var.project_id
}

output "region" {
  description = "GCP region of the production resources."
  value       = var.region
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name used by the Cloud SQL Auth Proxy / connector."
  value       = module.cloud_sql.connection_name
}

output "cloud_sql_private_ip" {
  description = "Private IP address of the Cloud SQL instance."
  value       = module.cloud_sql.private_ip_address
}

output "db_password_secret_id" {
  description = "Secret Manager resource id of the Cloud SQL application password."
  value       = module.secret_manager.db_password_secret_id
  sensitive   = true
}

output "app_secret_id" {
  description = "Secret Manager resource id of the application secret."
  value       = module.secret_manager.app_secret_secret_id
  sensitive   = true
}

output "token_encryption_key_secret_id" {
  description = "Secret Manager resource id of the OAuth token encryption key."
  value       = module.secret_manager.token_encryption_key_secret_id
  sensitive   = true
}

output "object_store_bucket" {
  description = "GCS bucket used as the S3-compatible object store."
  value       = module.gcs.object_store_bucket_url
}

output "backup_bucket" {
  description = "GCS bucket used for database backups."
  value       = module.gcs.backup_bucket_url
}

output "kms_crypto_key_id" {
  description = "KMS crypto key resource id used as the object store CMEK."
  value       = module.kms.crypto_key_id
}

output "vpc_network_id" {
  description = "Self link of the production VPC network."
  value       = module.vpc.network_id
}

output "vpc_connector_id" {
  description = "Self link of the serverless VPC connector."
  value       = module.vpc.connector_id
}

output "dns_zone_name_servers" {
  description = "Authoritative name servers of the Cloud DNS managed zone."
  value       = module.dns_tls.name_servers
}

output "ssl_certificate_id" {
  description = "Resource id of the Google-managed SSL certificate."
  value       = module.dns_tls.ssl_certificate_id
}

output "entra_application_client_id" {
  description = "Client (application) id of the Microsoft Entra application registration."
  value       = module.entra_app.client_id
}

output "entra_application_object_id" {
  description = "Object id of the Microsoft Entra application registration."
  value       = module.entra_app.object_id
}

output "entra_service_principal_id" {
  description = "Object id of the Microsoft Entra service principal."
  value       = module.entra_app.service_principal_id
}

output "workload_identity_pool_id" {
  description = "Fully qualified id of the Workload Identity Pool."
  value       = module.workload_identity.pool_id
}

output "github_actions_service_account_email" {
  description = "Service account email GitHub Actions impersonates via OIDC."
  value       = module.workload_identity.service_account_email
}
