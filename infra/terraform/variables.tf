# Root input variables for the WorkBuddy production infrastructure.
# Each variable carries a description and an explicit type so the configuration
# is self-documenting and fails fast on misconfiguration.

variable "project_id" {
  type        = string
  description = "GCP project id that hosts the WorkBuddy production infrastructure."
}

variable "region" {
  type        = string
  description = "GCP region for regional resources (Cloud SQL, GCS multi-region fallback, VPC subnetwork)."
  default     = "asia-east2"
}

variable "environment" {
  type        = string
  description = "Deployment environment label. Must be 'production' for this stack."
  default     = "production"

  validation {
    condition     = var.environment == "production"
    error_message = "This stack is intended for the production environment only."
  }
}

# --- Cloud SQL ----------------------------------------------------------------

variable "db_instance_name" {
  type        = string
  description = "Name of the Cloud SQL PostgreSQL instance."
  default     = "workbuddy-prod"
}

variable "db_name" {
  type        = string
  description = "Application database name created inside the Cloud SQL instance."
  default     = "workbuddy"
}

variable "db_user" {
  type        = string
  description = "Application database user granted access to the application database."
  default     = "workbuddy"
}

variable "db_tier" {
  type        = string
  description = "Cloud SQL machine tier (db-custom-VCPU-MEM_MB or a predefined tier)."
  default     = "db-custom-4-15360"
}

variable "db_availability_type" {
  type        = string
  description = "Cloud SQL availability type. REGIONAL provides HA with synchronous standby."
  default     = "REGIONAL"
}

variable "db_pg_version" {
  type        = string
  description = "PostgreSQL major version. WorkBuddy requires PostgreSQL 16."
  default     = "POSTGRES_16"
}

variable "db_disk_size_gb" {
  type        = number
  description = "Cloud SQL disk size in GB."
  default     = 100
}

# --- Networking ---------------------------------------------------------------

variable "vpc_name" {
  type        = string
  description = "Name of the production VPC network."
  default     = "workbuddy-prod-vpc"
}

variable "subnet_cidr" {
  type        = string
  description = "Primary subnetwork CIDR range for the production VPC."
  default     = "10.20.0.0/20"
}

variable "sql_private_services_range" {
  type        = string
  description = "CIDR range allocated to the Cloud SQL private services access connection."
  default     = "10.30.0.0/24"
}

variable "vpc_connector_cidr" {
  type        = string
  description = "CIDR range used by the serverless VPC connector."
  default     = "10.40.0.0/28"
}

variable "vpc_connector_machine_type" {
  type        = string
  description = "Machine type for the serverless VPC connector."
  default     = "e2-micro"
}

# --- Object storage / encryption ---------------------------------------------

variable "object_store_bucket" {
  type        = string
  description = "GCS bucket used as the S3-compatible object store for artifacts."
  default     = "workbuddy-prod-objects"
}

variable "backup_bucket" {
  type        = string
  description = "GCS bucket used for database backups and disaster recovery exports."
  default     = "workbuddy-prod-backups"
}

variable "kms_key_ring_name" {
  type        = string
  description = "Name of the KMS key ring that holds CMEK keys for storage encryption."
  default     = "workbuddy-prod"
}

variable "kms_crypto_key_name" {
  type        = string
  description = "KMS crypto key used as the CMEK for the object store bucket."
  default     = "object-store-cmek"
}

variable "storage_retention_days" {
  type        = number
  description = "Lifecycle retention (days) before noncurrent object versions are deleted."
  default     = 90
}

# --- DNS / TLS ----------------------------------------------------------------

variable "dns_zone_name" {
  type        = string
  description = "Name of the Cloud DNS managed zone."
  default     = "workbuddy-prod"
}

variable "dns_domain" {
  type        = string
  description = "Root DNS domain managed by the Cloud DNS zone (e.g. workbuddy.example.com)."
}

variable "dns_a_record_name" {
  type        = string
  description = "FQDN of the A record pointing at the production ingress (e.g. api.workbuddy.example.com)."
}

variable "dns_a_record_address" {
  type        = string
  description = "Static IPv4 address for the production A record (load balancer frontend)."
}

variable "ssl_certificate_domain" {
  type        = string
  description = "Domain covered by the Google-managed SSL certificate."
}

# --- Mail provider apps -------------------------------------------------------

variable "gmail_redirect_uri" {
  type        = string
  description = "OAuth redirect URI for the Gmail application. Must end with /v1/connectors/gmail/callback."
  default     = "https://api.workbuddy.example.com/v1/connectors/gmail/callback"
}

variable "gmail_pubsub_topic" {
  type        = string
  description = "Pub/Sub topic name used for Gmail push notifications (manual Google Cloud setup)."
  default     = "workbuddy-gmail-notify"
}

variable "graph_redirect_uri" {
  type        = string
  description = "OAuth redirect URI for the Microsoft Graph / Entra application. Must end with /v1/connectors/graph/callback."
  default     = "https://api.workbuddy.example.com/v1/connectors/graph/callback"
}

variable "entra_display_name" {
  type        = string
  description = "Display name for the Microsoft Entra ID application registration."
  default     = "WorkBuddy Production"
}

variable "entra_owner_object_ids" {
  type        = list(string)
  description = "Object IDs of Entra owners to attach to the application registration."
  default     = []
}

# --- Workload Identity Federation --------------------------------------------

variable "workload_identity_pool_id" {
  type        = string
  description = "ID of the GCP Workload Identity Pool used for GitHub Actions OIDC federation."
  default     = "github-actions"
}

variable "workload_identity_provider_id" {
  type        = string
  description = "ID of the Workload Identity Pool Provider that trusts the GitHub repo."
  default     = "github"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository in ORG/REPO form that is allowed to assume the workload identity (e.g. acme/workbuddy)."
}

variable "github_actions_service_account" {
  type        = string
  description = "GCP service account that GitHub Actions impersonates via workload identity federation."
  default     = "github-actions-deployer"
}

# --- Observability ------------------------------------------------------------

variable "grafana_version" {
  type        = string
  description = "Grafana version tag used by the managed Grafana deployment (placeholder for future observability module)."
  default     = "10.4.0"
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels applied to all supported resources."
  default = {
    app         = "workbuddy"
    environment = "production"
    managed_by  = "terraform"
  }
}
