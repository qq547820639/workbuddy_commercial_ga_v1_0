variable "project_id" {
  type        = string
  description = "GCP project id hosting the buckets."
}

variable "region" {
  type        = string
  description = "GCP region (location) for the buckets."
}

variable "object_store_bucket" {
  type        = string
  description = "Name of the object store bucket."
}

variable "backup_bucket" {
  type        = string
  description = "Name of the backup bucket."
}

variable "kms_key_id" {
  type        = string
  description = "Resource id of the KMS CMEK crypto key used for bucket encryption."
}

variable "retention_days" {
  type        = number
  description = "Retention window (days) before noncurrent/old objects are deleted."
  default     = 90
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
