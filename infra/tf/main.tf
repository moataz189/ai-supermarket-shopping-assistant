# Structure adapted from polyaifursa's infra/tf/main.tf: one root module wiring a public
# VPC registry module + this project's own alerting/k8s-cluster/ingress modules,
# workspace-tagged, with an AMI looked up by name from the Packer build.
#
# Terraform state: local by default (see the commented `backend "s3"` block below), not
# the reference's real S3 backend — this project's own decision (documented, not an
# oversight) is to keep state local for now (gitignored, risk noted) and keep the backend
# block ready to switch on later; an active S3 backend also cannot `terraform init`
# without a real bucket already existing, which would block even static
# validation (fmt/validate) until one is manually created out of band.
terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # backend "s3" {
  #   bucket         = "<your-unique-bucket-name>"
  #   key            = "supermarket-assistant/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = terraform.workspace
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name = "${var.project_name}-${terraform.workspace}-vpc"
  cidr = var.vpc_cidr

  azs            = slice(data.aws_availability_zones.available.names, 0, 2)
  public_subnets = [cidrsubnet(var.vpc_cidr, 4, 0), cidrsubnet(var.vpc_cidr, 4, 1)]

  # No NAT/VPN gateway — control-plane and worker nodes run directly in the public
  # subnets with public IPs, matching the reference architecture's cost/simplicity
  # trade-off (a NAT Gateway's ongoing per-hour + per-GB cost isn't worth it for a small,
  # cost-conscious MVP cluster where nothing needs to be network-isolated from the
  # internet beyond the security groups already restricting access).
  enable_nat_gateway = false
  enable_vpn_gateway = false

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  tags = { Project = var.project_name }
}

# The Packer-built AMI (infra/packer/k8s-node.pkr.hcl) — looked up by name prefix so a
# freshly-built AMI is picked up automatically on the next apply without editing any
# Terraform. custom_ami_id overrides this when set.
data "aws_ami" "k8s_node" {
  count       = var.custom_ami_id == null ? 1 : 0
  most_recent = true
  owners      = ["self"]

  filter {
    name   = "name"
    values = ["${var.project_name}-k8s-node-*"]
  }
}

locals {
  ami_id = coalesce(var.custom_ami_id, try(data.aws_ami.k8s_node[0].id, null))

  # Every public hostname this project's ALB/certificate serves — computed from
  # variables (never hardcoded literals), unlike the reference's own locals block, which
  # hardcodes five literal *.fursa.click strings directly.
  dev_hostname        = coalesce(var.dev_hostname, "${var.subdomain_prefix}-dev.${var.route53_zone_name}")
  prod_hostname       = coalesce(var.prod_hostname, "${var.subdomain_prefix}-prod.${var.route53_zone_name}")
  grafana_hostname    = coalesce(var.grafana_hostname, "grafana.${var.route53_zone_name}")
  prometheus_hostname = coalesce(var.prometheus_hostname, "prometheus.${var.route53_zone_name}")
  argocd_hostname     = coalesce(var.argocd_hostname, "argocd.${var.route53_zone_name}")

  ingress_hostnames = [
    local.dev_hostname,
    local.prod_hostname,
    local.grafana_hostname,
    local.prometheus_hostname,
    local.argocd_hostname,
  ]
}

module "alerting" {
  source = "./modules/alerting"

  project_name = var.project_name
  alert_email  = var.alert_email
}

module "k8s_cluster" {
  source = "./modules/k8s-cluster"

  project_name = var.project_name
  region       = var.region
  vpc_id       = module.vpc.vpc_id
  vpc_cidr     = var.vpc_cidr
  subnet_ids   = module.vpc.public_subnets
  admin_cidr   = var.admin_cidr
  ami_id       = local.ami_id
  key_name     = var.key_name

  control_plane_instance_type = var.control_plane_instance_type
  worker_instance_type        = var.worker_instance_type
  worker_min_size             = var.worker_min_size
  worker_max_size             = var.worker_max_size
  worker_desired_capacity     = var.worker_desired_capacity

  sns_topic_arn = module.alerting.topic_arn
}

module "ingress" {
  source = "./modules/ingress"
  count  = var.enable_ingress ? 1 : 0

  project_name             = var.project_name
  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.public_subnets
  route53_zone_name        = var.route53_zone_name
  hostnames                = local.ingress_hostnames
  worker_security_group_id = module.k8s_cluster.worker_security_group_id
  worker_asg_name          = module.k8s_cluster.worker_asg_name
}
