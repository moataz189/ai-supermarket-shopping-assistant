variable "region" {
  type    = string
  default = "il-central-1"
}

variable "project_name" {
  type    = string
  default = "supermarket-assistant-retailer-cart"
}

variable "admin_cidr" {
  description = "Your IP in CIDR form, e.g. \"203.0.113.4/32\" (get it with: curl -s ifconfig.me) — used for SSH access only. No default: never accidentally left open."
  type        = string
}

variable "route53_zone_name" {
  description = "Existing Route53 public hosted zone, e.g. \"fursa.click\" — same zone the us-east-1 stack already manages. Route53 is global, so this has no dependency on that stack's state."
  type        = string
}

variable "hostname" {
  description = "Full hostname to create for this instance, e.g. \"retailer-cart.fursa.click\"."
  type        = string
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}
