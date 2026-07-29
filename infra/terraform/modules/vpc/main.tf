# =============================================================================
# VPC - production network, private services access, serverless connector
# =============================================================================
#
# Creates:
#   * A custom-mode VPC network and a regional subnetwork
#   * A global private services access IP range for Cloud SQL
#   * A VPC peering connection (servicenetworking) so Cloud SQL gets a private IP
#   * A serverless VPC connector so Cloud Run / serverless workloads reach the
#     private Cloud SQL instance without exposing it publicly
#
# Cloud SQL depends on the private services access existing, so this module is
# applied before the cloud_sql module (see root main.tf depends_on).
# =============================================================================

# Custom-mode VPC network.
resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = var.vpc_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

# Regional subnetwork for the production workloads.
resource "google_compute_subnetwork" "subnet" {
  project                  = var.project_id
  name                     = "${var.vpc_name}-subnet"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

# Global address range reserved for Cloud SQL private services access.
resource "google_compute_global_address" "sql_private_services" {
  project      = var.project_id
  name         = "google-managed-services-${var.vpc_name}"
  purpose      = "VPC_PEERING"
  address_type = "INTERNAL"
  prefix_length = split("/", var.sql_private_services_range)[1]
  address      = cidrhost(var.sql_private_services_range, 0)
  network      = google_compute_network.vpc.id
}

# Private services access peering. Lets Google-managed services (Cloud SQL)
# reach the VPC over a private connection without public IP.
resource "google_service_networking_connection" "sql_private_services" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_private_services.name]
}

# Serverless VPC connector so serverless compute (Cloud Run / functions) can
# reach the private Cloud SQL instance.
resource "google_vpc_access_connector" "main" {
  project        = var.project_id
  name           = var.vpc_connector_name
  region         = var.region
  network        = google_compute_network.vpc.name
  ip_cidr_range  = var.vpc_connector_cidr
  machine_type   = var.vpc_connector_machine_type
  min_instances  = 2
  max_instances  = 3
}
