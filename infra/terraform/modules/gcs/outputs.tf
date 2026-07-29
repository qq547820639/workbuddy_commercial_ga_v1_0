output "object_store_bucket_name" {
  description = "Name of the object store bucket."
  value       = google_storage_bucket.object_store.name
}

output "object_store_bucket_url" {
  description = "gs:// URL of the object store bucket."
  value       = google_storage_bucket.object_store.url
}

output "backup_bucket_name" {
  description = "Name of the backup bucket."
  value       = google_storage_bucket.backup.name
}

output "backup_bucket_url" {
  description = "gs:// URL of the backup bucket."
  value       = google_storage_bucket.backup.url
}
