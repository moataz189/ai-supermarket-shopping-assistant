output "vpc_id" {
  value = module.vpc.vpc_id
}

output "control_plane_public_ip" {
  value = module.k8s_cluster.control_plane_public_ip
}

output "control_plane_name" {
  value = module.k8s_cluster.control_plane_name
}

output "worker_public_ips" {
  value = module.k8s_cluster.worker_public_ips
}

output "worker_asg_name" {
  value = module.k8s_cluster.worker_asg_name
}

output "worker_launch_template_id" {
  value = module.k8s_cluster.worker_launch_template_id
}

output "worker_launch_template_name" {
  value = module.k8s_cluster.worker_launch_template_name
}

output "worker_instance_ids" {
  value = module.k8s_cluster.worker_instance_ids
}

output "ssm_join_command_parameter_name" {
  value = module.k8s_cluster.ssm_join_command_parameter_name
}

output "alerts_sns_topic_arn" {
  value = module.alerting.topic_arn
}

output "checkpoint_table_name" {
  description = "DynamoDB table name for CHECKPOINT_DYNAMODB_TABLE in infra/k8s/prod/backend/backend-deployment.yaml — deterministic (\"<project_name>-checkpoints\"), included here for convenience, not because the manifest needs to read it dynamically."
  value       = aws_dynamodb_table.langgraph_checkpoints.name
}

output "alb_dns_name" {
  value = var.enable_ingress ? module.ingress[0].alb_dns_name : null
}

output "ingress_hostnames" {
  value = local.ingress_hostnames
}

output "dev_url" {
  value = var.enable_ingress ? "https://${local.dev_hostname}" : null
}

output "prod_url" {
  value = var.enable_ingress ? "https://${local.prod_hostname}" : null
}

output "grafana_url" {
  value = var.enable_ingress ? "https://${local.grafana_hostname}" : null
}

output "prometheus_url" {
  value = var.enable_ingress ? "https://${local.prometheus_hostname}" : null
}

output "argocd_url" {
  value = var.enable_ingress ? "https://${local.argocd_hostname}" : null
}
