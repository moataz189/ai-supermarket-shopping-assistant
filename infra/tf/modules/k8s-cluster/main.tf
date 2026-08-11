# Adapted from polyaifursa's infra/tf/modules/k8s-cluster — same overall shape (security
# groups, control-plane/worker IAM roles, control-plane EC2 + worker launch
# template/ASG, SSM join-command coordination). Deliberate differences from that
# reference, per this project's own requirements:
#   - SSH (22) and the Kubernetes API (6443) are restricted to var.admin_cidr, not
#     0.0.0.0/0 — the reference's own SGs open both to the world.
#   - The join-command SSM parameter path is namespaced under var.project_name via a
#     variable, not the hardcoded literal "/moataz-k8s/join-command" the reference uses.
#   - No S3/image-bucket IAM (this project has no image-upload feature) and no ECR
#     read-only policy (images are published to Docker Hub, per this project's own CP12
#     design, not ECR).

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  ssm_join_command_parameter_name = "/${var.project_name}/join-command"
  ssm_join_command_parameter_arn  = "arn:${data.aws_partition.current.partition}:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_join_command_parameter_name}"
}

# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

resource "aws_security_group" "control_plane" {
  name        = "${var.project_name}-control-plane-sg"
  description = "kubeadm control-plane node"
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH (admin only)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  ingress {
    description = "Kubernetes API (admin only)"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  ingress {
    description = "Kubernetes API (in-VPC, for workers joining/talking to the API server)"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.project_name}-control-plane-sg" })
}

resource "aws_security_group" "workers" {
  name        = "${var.project_name}-workers-sg"
  description = "kubeadm worker nodes"

  ingress {
    description = "SSH (admin only)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.project_name}-workers-sg" })
}

resource "aws_security_group_rule" "control_plane_self" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  security_group_id        = aws_security_group.control_plane.id
  source_security_group_id = aws_security_group.control_plane.id
  description              = "Intra control-plane traffic"
}

resource "aws_security_group_rule" "control_plane_from_workers" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  security_group_id        = aws_security_group.control_plane.id
  source_security_group_id = aws_security_group.workers.id
  description              = "Cluster traffic from worker nodes"
}

resource "aws_security_group_rule" "workers_self" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  security_group_id        = aws_security_group.workers.id
  source_security_group_id = aws_security_group.workers.id
  description              = "Intra worker-to-worker traffic"
}

resource "aws_security_group_rule" "workers_from_control_plane" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  security_group_id        = aws_security_group.workers.id
  source_security_group_id = aws_security_group.control_plane.id
  description              = "Cluster traffic from the control-plane node"
}

# ---------------------------------------------------------------------------
# IAM — control plane
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "control_plane" {
  name               = "${var.project_name}-control-plane-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "control_plane_eks_cluster_policy" {
  role       = aws_iam_role.control_plane.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

data "aws_iam_policy_document" "control_plane_ssm_publish" {
  statement {
    sid       = "PublishJoinCommand"
    actions   = ["ssm:PutParameter", "ssm:GetParameter", "ssm:DeleteParameter"]
    resources = [local.ssm_join_command_parameter_arn]
  }
}

resource "aws_iam_role_policy" "control_plane_ssm_publish" {
  name   = "ssm-join-command"
  role   = aws_iam_role.control_plane.id
  policy = data.aws_iam_policy_document.control_plane_ssm_publish.json
}

resource "aws_iam_instance_profile" "control_plane" {
  name = "${var.project_name}-control-plane"
  role = aws_iam_role.control_plane.name
}

# ---------------------------------------------------------------------------
# IAM — workers
# ---------------------------------------------------------------------------

resource "aws_iam_role" "worker" {
  name               = "${var.project_name}-worker-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "worker_eks_worker_node_policy" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

# Not EKS-specific despite the "service-role/" path — grants exactly the volume attach/
# detach/create permissions the EBS CSI driver's controller pod needs, running here as a
# plain Deployment inheriting the worker instance profile's credentials (no IRSA/pod
# identity, since this is not EKS).
resource "aws_iam_role_policy_attachment" "worker_ebs_csi" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

data "aws_iam_policy_document" "worker_permissions" {
  statement {
    sid       = "ReadJoinCommand"
    actions   = ["ssm:GetParameter"]
    resources = [local.ssm_join_command_parameter_arn]
  }

  statement {
    sid       = "InvokeBedrockModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.bedrock_model_arns
  }

  statement {
    sid       = "PublishAlerts"
    actions   = ["sns:Publish"]
    resources = [var.sns_topic_arn]
  }

  # Minimum permissions langgraph-checkpoint-aws's DynamoDBSaver documents needing —
  # matches AWS's own published IAM policy for this exact package.
  statement {
    sid = "LangGraphCheckpointStore"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = [var.checkpoint_table_arn]
  }
}

resource "aws_iam_role_policy" "worker_permissions" {
  name   = "${var.project_name}-worker-app-permissions"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_permissions.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "${var.project_name}-worker"
  role = aws_iam_role.worker.name
}

# ---------------------------------------------------------------------------
# Control-plane EC2 instance
# ---------------------------------------------------------------------------

resource "aws_instance" "control_plane" {
  ami                    = var.ami_id
  instance_type          = var.control_plane_instance_type
  subnet_id              = var.subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.control_plane.id]
  iam_instance_profile   = aws_iam_instance_profile.control_plane.name
  key_name               = var.key_name

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size_gb
    encrypted   = true
  }

  user_data = templatefile("${path.module}/scripts/control-plane.sh", {
    region                          = var.region
    pod_network_cidr                = var.pod_network_cidr
    ssm_join_command_parameter_name = local.ssm_join_command_parameter_name
  })
  user_data_replace_on_change = true

  tags = merge(var.tags, {
    Name = "${var.project_name}-control-plane"
    Role = "control-plane"
  })
}

# ---------------------------------------------------------------------------
# Worker launch template + Auto Scaling Group
# ---------------------------------------------------------------------------

resource "aws_launch_template" "worker" {
  name_prefix   = "${var.project_name}-worker-"
  image_id      = var.ami_id
  instance_type = var.worker_instance_type
  key_name      = var.key_name

  iam_instance_profile {
    name = aws_iam_instance_profile.worker.name
  }

  vpc_security_group_ids = [aws_security_group.workers.id]

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_type           = "gp3"
      volume_size           = var.root_volume_size_gb
      encrypted             = true
      delete_on_termination = true
    }
  }

  user_data = base64encode(templatefile("${path.module}/scripts/worker.sh", {
    region                          = var.region
    ssm_join_command_parameter_name = local.ssm_join_command_parameter_name
  }))

  tag_specifications {
    resource_type = "instance"
    tags = merge(var.tags, {
      Name = "${var.project_name}-worker"
      Role = "worker"
    })
  }

  update_default_version = true

  depends_on = [aws_iam_role_policy.worker_permissions]
}

resource "aws_autoscaling_group" "worker" {
  name                = "${var.project_name}-workers-asg"
  min_size            = var.worker_min_size
  max_size            = var.worker_max_size
  desired_capacity    = var.worker_desired_capacity
  vpc_zone_identifier = var.subnet_ids

  health_check_type         = "EC2"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-worker"
    propagate_at_launch = true
  }
  tag {
    key                 = "Role"
    value               = "worker"
    propagate_at_launch = true
  }

  depends_on = [aws_instance.control_plane]

  # NOTE (matches the reference's own documented trade-off): scale-down leaves stale
  # NotReady Node objects requiring manual `kubectl delete node <name>` — no ASG
  # lifecycle-hook/Lambda cleanup is implemented, deliberately deprioritized for MVP scope.
  lifecycle {
    ignore_changes = [desired_capacity]
  }
}

data "aws_instances" "workers" {
  instance_tags = {
    Name = "${var.project_name}-worker"
  }
  instance_state_names = ["pending", "running"]

  depends_on = [aws_autoscaling_group.worker]
}
