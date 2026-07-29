# =============================================================================
# WorkBuddy Commercial GA - Production Infrastructure (Gap 3)
# =============================================================================
#
# Root module composing the production GCP + Microsoft Entra infrastructure:
#   * VPC, private services access and a serverless VPC connector
#   * Cloud SQL PostgreSQL 16 (REGIONAL HA, PITR, private IP, Secret Manager pw)
#   * Google Secret Manager secrets for all application credentials
#   * Cloud KMS CMEK key ring + crypto key
#   * GCS object store and backup buckets (CMEK, uniform access, lifecycle)
#   * Cloud DNS managed zone, A record and Google-managed SSL certificate
#   * Gmail API OAuth app configuration (placeholder - manual setup required)
#   * Microsoft Entra ID application registration (Mail.ReadShared / Mail.Send)
#   * GCP Workload Identity Federation for GitHub Actions OIDC (no long-lived keys)
#
# Closes PRODUCTION_GAPS.md item #3 (Google Cloud and Microsoft Entra production
# applications) and item #4 (production PostgreSQL, object storage, KMS/Secrets
# and DNS/TLS). See docs/CLOUD_SETUP_CHECKLIST.md and docs/IDENTITY_AND_ACCESS.md.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.47"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

# --- Providers ----------------------------------------------------------------

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# The Entra provider authenticates against the Microsoft Entra ID tenant that
# owns the WorkBuddy application registration. Configure credentials out of band
# (e.g. via ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID or a federated
# credential). Never commit tenant credentials to this repository.
provider "azuread" {
  # tenant_id and client credentials are provided through environment variables.
}

# =============================================================================
# Modules
# =============================================================================

# Secret Manager containers for all application credentials. Secret *values*
# are seeded out of band; only the db_password and graph_client_secret values
# are written as versions by this stack (see below).
module "secret_manager" {
  source = "./modules/secret_manager"

  project_id = var.project_id
  labels     = var.labels
}

# Cloud KMS key ring and CMEK crypto key for object storage encryption.
module "kms" {
  source = "./modules/kms"

  project_id       = var.project_id
  region           = var.region
  key_ring_name    = var.kms_key_ring_name
  crypto_key_name  = var.kms_crypto_key_name
  labels           = var.labels
}

# Production VPC, subnetwork, Cloud SQL private service connection and the
# serverless VPC connector. Created before Cloud SQL so the private services
# access range exists when the instance is provisioned.
module "vpc" {
  source = "./modules/vpc"

  project_id                    = var.project_id
  region                        = var.region
  vpc_name                      = var.vpc_name
  subnet_cidr                   = var.subnet_cidr
  sql_private_services_range    = var.sql_private_services_range
  vpc_connector_name            = "${var.vpc_name}-connector"
  vpc_connector_cidr            = var.vpc_connector_cidr
  vpc_connector_machine_type    = var.vpc_connector_machine_type
  labels                        = var.labels
}

# Generate a strong random password for the Cloud SQL application user and
# store it as a Secret Manager version. The plaintext is passed to the Cloud
# SQL module to create the user, and never written to a ConfigMap or log.
resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = module.secret_manager.db_password_secret_id
  secret_data = random_password.db_password.result
}

# Cloud SQL PostgreSQL 16 with REGIONAL HA, point-in-time recovery, private IP
# and a password sourced from Secret Manager.
module "cloud_sql" {
  source = "./modules/cloud_sql"

  project_id            = var.project_id
  region                = var.region
  instance_name         = var.db_instance_name
  db_name               = var.db_name
  db_user               = var.db_user
  db_password           = random_password.db_password.result
  db_tier               = var.db_tier
  availability_type     = var.db_availability_type
  pg_version            = var.db_pg_version
  disk_size_gb          = var.db_disk_size_gb
  network               = module.vpc.network_id
  labels                = var.labels

  # Cloud SQL private services access range must exist first.
  depends_on = [module.vpc]
}

# GCS object store and backup buckets. Both use the KMS CMEK for encryption,
# uniform bucket-level access and lifecycle policies.
module "gcs" {
  source = "./modules/gcs"

  project_id           = var.project_id
  region               = var.region
  object_store_bucket  = var.object_store_bucket
  backup_bucket        = var.backup_bucket
  kms_key_id           = module.kms.crypto_key_id
  retention_days       = var.storage_retention_days
  labels               = var.labels

  depends_on = [module.kms]
}

# Cloud DNS managed zone, A record and a Google-managed SSL certificate for the
# public HTTPS endpoint.
module "dns_tls" {
  source = "./modules/dns_tls"

  project_id            = var.project_id
  dns_zone_name         = var.dns_zone_name
  dns_domain            = var.dns_domain
  dns_a_record_name     = var.dns_a_record_name
  dns_a_record_address  = var.dns_a_record_address
  ssl_certificate_domain = var.ssl_certificate_domain
  labels                = var.labels
}

# Gmail API OAuth app configuration. This is a placeholder: the real Gmail OAuth
# consent screen, OAuth client, scopes and Pub/Sub watch must be created in the
# Google Cloud Console. See docs/GMAIL_SETUP.md.
module "gmail_app" {
  source = "./modules/gmail_app"

  project_id        = var.project_id
  region            = var.region
  redirect_uri      = var.gmail_redirect_uri
  pubsub_topic_name = var.gmail_pubsub_topic
  gmail_client_secret_id = module.secret_manager.gmail_client_secret_secret_id
  labels            = var.labels
}

# Microsoft Entra ID application registration with Mail.ReadShared and Mail.Send
# scoped permissions and a redirect URI. The generated client secret is stored
# in GCP Secret Manager (graph_client_secret).
module "entra_app" {
  source = "./modules/entra_app"

  display_name           = var.entra_display_name
  graph_redirect_uri     = var.graph_redirect_uri
  owner_object_ids       = var.entra_owner_object_ids
  graph_client_secret_id = module.secret_manager.graph_client_secret_secret_id
  labels                 = var.labels

  depends_on = [module.secret_manager]
}

# GCP Workload Identity Pool and Provider so GitHub Actions can authenticate to
# GCP via OIDC without long-lived service-account keys.
module "workload_identity" {
  source = "./modules/workload_identity"

  project_id                          = var.project_id
  pool_id                             = var.workload_identity_pool_id
  provider_id                         = var.workload_identity_provider_id
  github_repo                         = var.github_repo
  github_actions_service_account      = var.github_actions_service_account
  labels                              = var.labels
}
