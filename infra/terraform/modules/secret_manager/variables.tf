variable "project_id" {
  type        = string
  description = "GCP project id hosting the Secret Manager secrets."
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
