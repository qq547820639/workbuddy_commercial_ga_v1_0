output "key_ring_id" {
  description = "Resource id of the KMS key ring."
  value       = google_kms_key_ring.main.id
}

output "crypto_key_id" {
  description = "Resource id of the CMEK crypto key (used by the GCS module)."
  value       = google_kms_crypto_key.object_store.id
}

output "crypto_key_name" {
  description = "Fully qualified crypto key name."
  value       = google_kms_crypto_key.object_store.name
}
