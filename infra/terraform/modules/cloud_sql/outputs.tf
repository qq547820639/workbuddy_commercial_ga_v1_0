output "instance_name" {
  description = "Name of the Cloud SQL instance."
  value       = google_sql_database_instance.primary.name
}

output "connection_name" {
  description = "Cloud SQL connection name for the Auth Proxy / connector."
  value       = google_sql_database_instance.primary.connection_name
}

output "private_ip_address" {
  description = "Private IP address of the Cloud SQL instance."
  value       = google_sql_database_instance.primary.private_ip_address
}

output "database_name" {
  description = "Application database name."
  value       = google_sql_database.app.name
}

output "database_user" {
  description = "Application database user."
  value       = google_sql_user.app.name
}

output "self_link" {
  description = "Self link of the Cloud SQL instance."
  value       = google_sql_database_instance.primary.self_link
}
