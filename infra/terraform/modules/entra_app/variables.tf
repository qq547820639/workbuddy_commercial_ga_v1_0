variable "display_name" {
  type        = string
  description = "Display name for the Microsoft Entra application registration."
}

variable "graph_redirect_uri" {
  type        = string
  description = "OAuth redirect URI. Must end with /v1/connectors/graph/callback."
}

variable "owner_object_ids" {
  type        = list(string)
  description = "Object IDs of Entra owners to attach to the application and service principal."
  default     = []
}

variable "graph_client_secret_id" {
  type        = string
  description = "GCP Secret Manager resource id where the Entra client secret is stored."
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels (applied to GCP Secret Manager version only)."
  default     = {}
}
