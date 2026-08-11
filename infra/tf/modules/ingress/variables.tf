variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Public subnets the ALB is placed in."
  type        = list(string)
}

variable "route53_zone_name" {
  description = "Existing, externally-managed Route53 public hosted zone name (e.g. \"example.com\") — this module looks it up, it does not create the zone."
  type        = string
}

variable "hostnames" {
  description = "Every public hostname this ALB/certificate should serve. hostnames[0] becomes the ACM certificate's primary domain_name; the rest are Subject Alternative Names."
  type        = list(string)

  validation {
    condition     = length(var.hostnames) > 0
    error_message = "At least one hostname is required."
  }
}

variable "worker_security_group_id" {
  description = "Workers' security group id — a rule is added allowing the ALB to reach worker_node_port on it."
  type        = string
}

variable "worker_asg_name" {
  description = "Worker Auto Scaling Group name, attached to the target group so autoscaled instances register/deregister automatically."
  type        = string
}

variable "worker_node_port" {
  description = "The NodePort ingress-nginx's controller Service listens on (see infra/helm/ingress-nginx-values.yaml) — must match exactly."
  type        = number
  default     = 30080
}

variable "tags" {
  type    = map(string)
  default = {}
}
