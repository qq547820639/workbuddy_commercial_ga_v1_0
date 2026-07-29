variable "project_id" {
  type        = string
  description = "GCP project id hosting the DNS zone and SSL certificate."
}

variable "dns_zone_name" {
  type        = string
  description = "Name of the Cloud DNS managed zone."
}

variable "dns_domain" {
  type        = string
  description = "Root DNS domain managed by the zone (without trailing dot)."
}

variable "dns_a_record_name" {
  type        = string
  description = "FQDN of the A record (with trailing dot), e.g. api.workbuddy.example.com."
}

variable "dns_a_record_address" {
  type        = string
  description = "IPv4 address the A record points at (load balancer frontend)."
}

variable "ssl_certificate_domain" {
  type        = string
  description = "Domain covered by the Google-managed SSL certificate."
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
