# =============================================================================
# GCS - object storage and backup buckets (Gap 3 / Gap 4)
# =============================================================================
#
# Two buckets:
#   * object store  - S3-compatible storage for WorkBuddy artifacts/evidence
#     (mapped via WORKBUDDY_OBJECT_STORE_PROVIDER=s3, see docs/DEPLOYMENT.md)
#   * backup bucket  - database backup and disaster-recovery exports
#
# Both buckets use:
#   * CMEK encryption with the KMS crypto key from the kms module
#   * uniform bucket-level access (no legacy ACLs)
#   * versioning (object store) and lifecycle rules to retire stale versions
#   * public access prevention enforced
# =============================================================================

# Object store bucket for application artifacts and gate evidence.
resource "google_storage_bucket" "object_store" {
  project                     = var.project_id
  name                        = var.object_store_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  public_access_prevention = "enforced"

  versioning {
    enabled = true
  }

  # CMEK encryption with the KMS crypto key from the kms module.
  encryption {
    default_kms_key = var.kms_key_id
  }

  # Retire noncurrent versions and abort incomplete multipart uploads.
  lifecycle_rule {
    condition {
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = var.retention_days
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type          = "AbortIncompleteMultipartUpload"
    }
  }

  labels = var.labels

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [var.kms_key_id]
}

# Backup bucket for database backups and restore exports.
resource "google_storage_bucket" "backup" {
  project                     = var.project_id
  name                        = var.backup_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  public_access_prevention = "enforced"

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key = var.kms_key_id
  }

  # Delete backups older than the retention window; object lock should be set
  # out of band if regulatory immutability is required.
  lifecycle_rule {
    condition {
      age = var.retention_days
    }
    action {
      type = "Delete"
    }
  }

  labels = var.labels

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [var.kms_key_id]
}
