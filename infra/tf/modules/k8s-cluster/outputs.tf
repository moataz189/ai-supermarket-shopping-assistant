output "control_plane_instance_id" {
  value = aws_instance.control_plane.id
}

output "control_plane_public_ip" {
  value = aws_instance.control_plane.public_ip
}

output "control_plane_private_ip" {
  value = aws_instance.control_plane.private_ip
}

output "control_plane_name" {
  value = aws_instance.control_plane.tags["Name"]
}

output "worker_security_group_id" {
  value = aws_security_group.workers.id
}

output "control_plane_security_group_id" {
  value = aws_security_group.control_plane.id
}

output "worker_asg_name" {
  value = aws_autoscaling_group.worker.name
}

output "worker_launch_template_id" {
  value = aws_launch_template.worker.id
}

output "worker_launch_template_name" {
  value = aws_launch_template.worker.name
}

output "worker_instance_ids" {
  value = data.aws_instances.workers.ids
}

output "worker_public_ips" {
  value = data.aws_instances.workers.public_ips
}

output "worker_private_ips" {
  value = data.aws_instances.workers.private_ips
}

output "ssm_join_command_parameter_name" {
  value = local.ssm_join_command_parameter_name
}
