# =============================================================================
# Cloud KMS - customer-managed encryption key (CMEK) for object storage (Gap 3)
# =============================================================================
#
# Creates a KMS key ring and a symmetric crypto key used as the CMEK for the
# GCS object store and backup buckets. Customer-managed keys give the platform
# team independent key revocation and audit control over data-at-rest encryption
# beyond the default Google-managed keys.
# =============================================================================

# Regional key ring. Key rings are immutable containers and region-scoped.
resource "google_kms_key_ring" "main" {
  project  = var.project_id
  name     = var.key_ring_name
  location = var.region
}

# Symmetric encryption crypto key (ENCRYPT_DECRYPT) with automatic rotation.
resource "google_kms_crypto_key" "object_store" {
  project            = var.project_id
  name               = var.crypto_key_name
  key_ring           = google_kms_key_ring.main.id
  purpose            = "ENCRYPT_DECRYPT"
  rotation_period    = "7776000s" # 90 days
  destroy_scheduled_duration = "86400s"

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = "SOFTWARE"
  }

  labels = var.labels

  lifecycle {
    prevent_destroy = true
  }
}
