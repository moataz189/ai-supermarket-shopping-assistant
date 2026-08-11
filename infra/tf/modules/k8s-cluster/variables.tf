variable "project_name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "admin_cidr" {
  description = "CIDR allowed to reach SSH (22) and the Kubernetes API (6443) — e.g. \"203.0.113.4/32\". No default: never accidentally left open to the internet."
  type        = string
}

variable "ami_id" {
  type = string
}

variable "key_name" {
  type = string
}

variable "control_plane_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "worker_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "root_volume_size_gb" {
  type    = number
  default = 20
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

variable "pod_network_cidr" {
  type    = string
  default = "192.168.0.0/16"
}

variable "sns_topic_arn" {
  description = "Alerts SNS topic ARN (from the alerting module) — Alertmanager (running as a worker pod, kube-prometheus-stack) publishes to it directly via SigV4, so the worker role needs sns:Publish scoped to this ARN."
  type        = string
}

variable "bedrock_model_arns" {
  description = "Resource ARNs/patterns the worker role may call bedrock:InvokeModel* against. The app's BEDROCK_MODEL_ID is runtime-configurable (app/agent/llm.py), so this defaults to every foundation model in-region rather than a fixed allowlist."
  type        = list(string)
  default     = ["arn:aws:bedrock:*::foundation-model/*"]
}

variable "checkpoint_table_arn" {
  description = "LangGraph checkpoint DynamoDB table ARN (from the root module) — the prod backend pod (CHECKPOINTER_BACKEND=dynamodb) reads/writes it via the worker instance profile, no IRSA."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
