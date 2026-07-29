variable "project_id" {
  type        = string
  description = "GCP project id where the Gmail API is enabled (manual setup)."
}

variable "region" {
  type        = string
  description = "GCP region (used for Pub/Sub topic location reference)."
}

variable "redirect_uri" {
  type        = string
  description = "OAuth redirect URI. Must end with /v1/connectors/gmail/callback."
}

variable "pubsub_topic_name" {
  type        = string
  description = "Pub/Sub topic name used for Gmail push notifications (manual setup)."
}

variable "gmail_client_secret_id" {
  type        = string
  description = "Secret Manager resource id where the Gmail client secret is seeded (manual)."
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
