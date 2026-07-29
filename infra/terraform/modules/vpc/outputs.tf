output "network_id" {
  description = "Self link / id of the VPC network."
  value       = google_compute_network.vpc.id
}

output "network_name" {
  description = "Name of the VPC network."
  value       = google_compute_network.vpc.name
}

output "subnet_id" {
  description = "Self link of the subnetwork."
  value       = google_compute_subnetwork.subnet.id
}

output "subnet_name" {
  description = "Name of the subnetwork."
  value       = google_compute_subnetwork.subnet.name
}

output "sql_private_services_range" {
  description = "CIDR range reserved for Cloud SQL private services access."
  value       = google_compute_global_address.sql_private_services.address
}

output "connector_id" {
  description = "Self link of the serverless VPC connector."
  value       = google_vpc_access_connector.main.id
}

output "connector_name" {
  description = "Name of the serverless VPC connector."
  value       = google_vpc_access_connector.main.name
}
