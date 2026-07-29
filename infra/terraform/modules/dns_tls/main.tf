# =============================================================================
# Cloud DNS + Google-managed TLS (Gap 3 / Gap 4)
# =============================================================================
#
# Creates:
#   * A Cloud DNS managed zone for the production domain
#   * An A record pointing the public API hostname at the load balancer IP
#   * A Google-managed SSL certificate for the HTTPS frontend
#
# Note: the managed zone must be delegated from the registrar before the SSL
# certificate can be issued (Google verifies domain control via DNS). This is a
# MANUAL STEP recorded in docs/CLOUD_SETUP_CHECKLIST.md.
# =============================================================================

# Managed DNS zone for the production domain.
resource "google_dns_managed_zone" "zone" {
  project     = var.project_id
  name        = var.dns_zone_name
  dns_name    = "${var.dns_domain}."
  description = "WorkBuddy production DNS zone for ${var.dns_domain}"
  visibility  = "public"

  dnssec_config {
    state = "on"
  }
}

# A record for the public API hostname pointing at the load balancer frontend.
resource "google_dns_record_set" "api_a" {
  project      = var.project_id
  name         = var.dns_a_record_name
  type         = "A"
  ttl          = 300
  managed_zone = google_dns_managed_zone.zone.name
  rrdatas      = [var.dns_a_record_address]
}

# Google-managed SSL certificate for the HTTPS frontend. Google provisions and
# renews the certificate automatically; it becomes ACTIVE once DNS is delegated
# and the load balancer serves the domain.
resource "google_compute_managed_ssl_certificate" "api" {
  project = var.project_id
  name    = "${var.dns_zone_name}-ssl"

  managed {
    domains = [var.ssl_certificate_domain]
  }
}
