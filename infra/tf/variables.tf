variable "region" {
  type = string
}

variable "project_name" {
  type    = string
  default = "supermarket-assistant"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "admin_cidr" {
  description = "Your IP in CIDR form, e.g. \"203.0.113.4/32\" (get it with: curl -s ifconfig.me) — used for SSH and Kubernetes API access. No default: never accidentally left open."
  type        = string
}

variable "key_name" {
  type    = string
  default = "supermarket-assistant"
}

variable "control_plane_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "worker_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "worker_min_size" {
  type    = number
  default = 1
}

variable "worker_max_size" {
  type    = number
  default = 3
}

variable "worker_desired_capacity" {
  type    = number
  default = 1
}

variable "custom_ami_id" {
  description = "Override the auto-discovered Packer AMI (looked up by name prefix \"<project_name>-k8s-node-\") with a specific AMI id. Leave null (the default) to always use the most recently built one."
  type        = string
  default     = null
}

variable "enable_ingress" {
  description = "Whether to provision the ALB/ACM/Route53 stack (modules/ingress). Set to false to validate/plan just the cluster itself without needing a real Route53 hosted zone."
  type        = bool
  default     = true
}

variable "route53_zone_name" {
  description = "Existing Route53 public hosted zone this project's hostnames are created in, e.g. \"example.com\". Required when enable_ingress = true. No default — never silently reuses someone else's domain."
  type        = string
  default     = ""
}

variable "subdomain_prefix" {
  description = "Prefix used to build the default dev/prod hostnames, e.g. \"supermarket\" -> supermarket-dev.<zone>, supermarket-prod.<zone>. Override the individual *_hostname variables instead for a different naming convention."
  type        = string
  default     = "supermarket"
}

variable "dev_hostname" {
  type    = string
  default = null
}

variable "prod_hostname" {
  type    = string
  default = null
}

variable "grafana_hostname" {
  type    = string
  default = null
}

variable "prometheus_hostname" {
  type    = string
  default = null
}

variable "argocd_hostname" {
  type    = string
  default = null
}

variable "alert_email" {
  description = "Email subscribed to the Alertmanager -> SNS alerts topic. No default. AWS sends a confirmation email after the first apply that must be manually confirmed before alerts deliver."
  type        = string
  default     = ""
  sensitive   = true
}
