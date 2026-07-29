variable "project_id" {
  type        = string
  description = "GCP project id hosting the KMS key ring."
}

variable "region" {
  type        = string
  description = "GCP region (location) for the KMS key ring."
}

variable "key_ring_name" {
  type        = string
  description = "Name of the KMS key ring."
}

variable "crypto_key_name" {
  type        = string
  description = "Name of the CMEK crypto key for object storage encryption."
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
