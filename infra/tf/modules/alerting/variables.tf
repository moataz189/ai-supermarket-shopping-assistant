variable "project_name" {
  type = string
}

variable "alert_email" {
  description = "Email subscribed to the alerts SNS topic. No default — supply via a gitignored *.auto.tfvars or -var/CI secret, never a tracked tfvars file. AWS emails a confirmation link after the first apply; alerts do not deliver until it's clicked (SNS gives Terraform no visibility into confirmation status to wait on)."
  type        = string
  sensitive   = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
