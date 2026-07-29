variable "project_id" {
  type        = string
  description = "GCP project id hosting the Cloud SQL instance."
}

variable "region" {
  type        = string
  description = "GCP region for the Cloud SQL instance."
}

variable "instance_name" {
  type        = string
  description = "Name of the Cloud SQL instance."
}

variable "db_name" {
  type        = string
  description = "Application database name."
}

variable "db_user" {
  type        = string
  description = "Application database user."
}

variable "db_password" {
  type        = string
  description = "Application database password (generated and stored in Secret Manager by the root module)."
  sensitive   = true
}

variable "db_tier" {
  type        = string
  description = "Cloud SQL machine tier."
}

variable "availability_type" {
  type        = string
  description = "Cloud SQL availability type (REGIONAL for HA)."
}

variable "pg_version" {
  type        = string
  description = "PostgreSQL version. WorkBuddy requires POSTGRES_16."
}

variable "disk_size_gb" {
  type        = number
  description = "Disk size in GB."
}

variable "network" {
  type        = string
  description = "Self link of the VPC network used for the private IP connection."
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
