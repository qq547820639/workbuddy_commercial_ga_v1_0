output "zone_id" {
  description = "Resource id of the Cloud DNS managed zone."
  value       = google_dns_managed_zone.zone.id
}

output "zone_name" {
  description = "Name of the Cloud DNS managed zone."
  value       = google_dns_managed_zone.zone.name
}

output "name_servers" {
  description = "Authoritative name servers of the managed zone (delegate these at the registrar)."
  value       = google_dns_managed_zone.zone.name_servers
}

output "a_record_name" {
  description = "FQDN of the created A record."
  value       = google_dns_record_set.api_a.name
}

output "ssl_certificate_id" {
  description = "Resource id of the Google-managed SSL certificate."
  value       = google_compute_managed_ssl_certificate.api.id
}

output "ssl_certificate_name" {
  description = "Name of the Google-managed SSL certificate."
  value       = google_compute_managed_ssl_certificate.api.name
}
