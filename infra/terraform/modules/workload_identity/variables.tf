variable "project_id" {
  type        = string
  description = "GCP project id hosting the Workload Identity Pool."
}

variable "pool_id" {
  type        = string
  description = "Workload Identity Pool id."
}

variable "provider_id" {
  type        = string
  description = "Workload Identity Pool Provider id."
}

variable "github_repo" {
  type        = string
  description = "GitHub repository in ORG/REPO form allowed to impersonate the service account."
}

variable "github_actions_service_account" {
  type        = string
  description = "Account id of the GCP service account GitHub Actions impersonates."
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
