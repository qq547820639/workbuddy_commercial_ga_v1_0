variable "project_id" {
  type        = string
  description = "GCP project id hosting the VPC."
}

variable "region" {
  type        = string
  description = "GCP region for the subnetwork and serverless connector."
}

variable "vpc_name" {
  type        = string
  description = "Name of the VPC network."
}

variable "subnet_cidr" {
  type        = string
  description = "CIDR range of the primary subnetwork."
}

variable "sql_private_services_range" {
  type        = string
  description = "CIDR range allocated to Cloud SQL private services access."
}

variable "vpc_connector_name" {
  type        = string
  description = "Name of the serverless VPC connector."
}

variable "vpc_connector_cidr" {
  type        = string
  description = "CIDR range used by the serverless VPC connector (/28 minimum)."
}

variable "vpc_connector_machine_type" {
  type        = string
  description = "Machine type for the serverless VPC connector."
  default     = "e2-micro"
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default     = {}
}
