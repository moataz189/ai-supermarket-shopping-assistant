# CP10 — Terraform + kubeadm Cluster on EC2

Spec milestone: M4. Depends on: CP9 (needs a built image to eventually deploy, though this
checkpoint itself only provisions infrastructure).

## Goal

Provision a self-managed (kubeadm, not EKS/not k3s) two-node Kubernetes cluster on AWS EC2
using Terraform: one control-plane node and one worker node, reachable via `kubectl` from
the developer's machine.

## Scope

Terraform only, plus the shell bootstrap scripts baked into EC2 user-data. No application
deployment yet (CP10). Local Terraform state is acceptable for this solo project (see Risks).

## Prerequisites (manual, one-time, outside Terraform)

- AWS credentials configured locally (`aws configure` or SSO), with permission to create
  EC2 instances, security groups, IAM roles, and SSM parameters.
- An EC2 key pair created in the target region: `aws ec2 create-key-pair --key-name
  supermarket-assistant --query 'KeyMaterial' --output text > ~/.ssh/supermarket-assistant.pem
  && chmod 400 ~/.ssh/supermarket-assistant.pem` (kept out of Terraform state deliberately).
- Your current public IP, for `admin_cidr` (e.g. `curl -s ifconfig.me`).

## Deliverables

- `terraform apply` creates a control-plane + worker EC2 pair; ~3–5 minutes after apply,
  `kubectl get nodes` (via a fetched kubeconfig) shows both `Ready`.

## Files to Create

```
infra/terraform/main.tf
infra/terraform/variables.tf
infra/terraform/outputs.tf
infra/terraform/user_data/control_plane.sh.tpl
infra/terraform/user_data/worker.sh.tpl
```

## Detailed Implementation Steps

1. Write `infra/terraform/variables.tf`:
   ```hcl
   variable "aws_region" {
     type    = string
     default = "us-east-1"
   }

   variable "admin_cidr" {
     description = "Your IP in CIDR form, e.g. 203.0.113.4/32 — used for SSH and API access."
     type        = string
   }

   variable "control_plane_instance_type" {
     type    = string
     default = "t3.medium"
   }

   variable "worker_instance_type" {
     type    = string
     default = "t3.medium"
   }

   variable "key_pair_name" {
     type    = string
     default = "supermarket-assistant"
   }
   ```
2. Write `infra/terraform/main.tf` — provider, default VPC lookup, security group, IAM role
   for cross-node join coordination via SSM, and the two instances:
   ```hcl
   terraform {
     required_version = ">= 1.5"
     required_providers {
       aws = { source = "hashicorp/aws", version = "~> 5.0" }
     }
   }

   provider "aws" {
     region = var.aws_region
   }

   data "aws_vpc" "default" { default = true }

   data "aws_subnets" "default" {
     filter {
       name   = "vpc-id"
       values = [data.aws_vpc.default.id]
     }
   }

   data "aws_ami" "ubuntu" {
     most_recent = true
     owners      = ["099720109477"] # Canonical
     filter {
       name   = "name"
       values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
     }
   }

   resource "aws_security_group" "cluster" {
     name   = "supermarket-assistant-cluster"
     vpc_id = data.aws_vpc.default.id

     ingress {
       description = "SSH"
       from_port   = 22
       to_port     = 22
       protocol    = "tcp"
       cidr_blocks = [var.admin_cidr]
     }

     ingress {
       description = "Kubernetes API"
       from_port   = 6443
       to_port     = 6443
       protocol    = "tcp"
       cidr_blocks = [var.admin_cidr]
     }

     ingress {
       description = "NodePort range for dev/prod service exposure"
       from_port   = 30000
       to_port     = 32767
       protocol    = "tcp"
       cidr_blocks = ["0.0.0.0/0"]
     }

     ingress {
       description = "Intra-cluster traffic"
       from_port   = 0
       to_port     = 0
       protocol    = "-1"
       self        = true
     }

     egress {
       from_port   = 0
       to_port     = 0
       protocol    = "-1"
       cidr_blocks = ["0.0.0.0/0"]
     }
   }

   resource "aws_iam_role" "node" {
     name = "supermarket-assistant-node"
     assume_role_policy = jsonencode({
       Version = "2012-10-17"
       Statement = [{
         Effect    = "Allow"
         Principal = { Service = "ec2.amazonaws.com" }
         Action    = "sts:AssumeRole"
       }]
     })
   }

   resource "aws_iam_role_policy" "ssm_join" {
     name = "ssm-join-parameter"
     role = aws_iam_role.node.id
     policy = jsonencode({
       Version = "2012-10-17"
       Statement = [{
         Effect   = "Allow"
         Action   = ["ssm:PutParameter", "ssm:GetParameter"]
         Resource = "arn:aws:ssm:*:*:parameter/supermarket-assistant/*"
       }]
     })
   }

   resource "aws_iam_instance_profile" "node" {
     name = "supermarket-assistant-node"
     role = aws_iam_role.node.name
   }

   resource "aws_instance" "control_plane" {
     ami                    = data.aws_ami.ubuntu.id
     instance_type          = var.control_plane_instance_type
     subnet_id              = data.aws_subnets.default.ids[0]
     vpc_security_group_ids = [aws_security_group.cluster.id]
     iam_instance_profile   = aws_iam_instance_profile.node.name
     key_name               = var.key_pair_name
     user_data = templatefile("${path.module}/user_data/control_plane.sh.tpl", {
       aws_region = var.aws_region
     })

     tags = { Name = "supermarket-assistant-control-plane", Role = "control-plane" }
   }

   resource "aws_instance" "worker" {
     ami                    = data.aws_ami.ubuntu.id
     instance_type          = var.worker_instance_type
     subnet_id              = data.aws_subnets.default.ids[0]
     vpc_security_group_ids = [aws_security_group.cluster.id]
     iam_instance_profile   = aws_iam_instance_profile.node.name
     key_name               = var.key_pair_name
     user_data = templatefile("${path.module}/user_data/worker.sh.tpl", {
       aws_region = var.aws_region
     })
     depends_on = [aws_instance.control_plane]

     tags = { Name = "supermarket-assistant-worker", Role = "worker" }
   }
   ```
3. Write `infra/terraform/user_data/control_plane.sh.tpl` (installs containerd + kubeadm,
   initializes the cluster, installs the Calico CNI, and publishes the join command via SSM
   so the worker node can retrieve it without manual copy-paste):
   ```bash
   #!/bin/bash
   set -euxo pipefail

   apt-get update
   apt-get install -y containerd apt-transport-https ca-certificates curl gpg awscli
   mkdir -p /etc/containerd
   containerd config default > /etc/containerd/config.toml
   sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
   systemctl restart containerd

   curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key \
     | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
   echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /" \
     > /etc/apt/sources.list.d/kubernetes.list
   apt-get update
   apt-get install -y kubelet kubeadm kubectl
   apt-mark hold kubelet kubeadm kubectl

   swapoff -a
   kubeadm init --pod-network-cidr=192.168.0.0/16

   mkdir -p /home/ubuntu/.kube
   cp /etc/kubernetes/admin.conf /home/ubuntu/.kube/config
   chown ubuntu:ubuntu /home/ubuntu/.kube/config

   export KUBECONFIG=/etc/kubernetes/admin.conf
   kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml

   JOIN_CMD=$(kubeadm token create --print-join-command)
   aws ssm put-parameter --region ${aws_region} \
     --name /supermarket-assistant/kubeadm-join-command \
     --type SecureString --value "$JOIN_CMD" --overwrite
   ```
4. Write `infra/terraform/user_data/worker.sh.tpl` (same package install, then polls SSM
   for the join command and joins):
   ```bash
   #!/bin/bash
   set -euxo pipefail

   apt-get update
   apt-get install -y containerd apt-transport-https ca-certificates curl gpg awscli
   mkdir -p /etc/containerd
   containerd config default > /etc/containerd/config.toml
   sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
   systemctl restart containerd

   curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key \
     | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
   echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /" \
     > /etc/apt/sources.list.d/kubernetes.list
   apt-get update
   apt-get install -y kubelet kubeadm kubectl
   apt-mark hold kubelet kubeadm kubectl

   swapoff -a

   for i in $(seq 1 30); do
     JOIN_CMD=$(aws ssm get-parameter --region ${aws_region} \
       --name /supermarket-assistant/kubeadm-join-command --with-decryption \
       --query 'Parameter.Value' --output text 2>/dev/null || true)
     if [ -n "$JOIN_CMD" ]; then break; fi
     sleep 10
   done

   eval "$JOIN_CMD"
   ```
5. Write `infra/terraform/outputs.tf`:
   ```hcl
   output "control_plane_public_ip" {
     value = aws_instance.control_plane.public_ip
   }

   output "worker_public_ip" {
     value = aws_instance.worker.public_ip
   }

   output "fetch_kubeconfig_command" {
     value = "scp -i ~/.ssh/${var.key_pair_name}.pem ubuntu@${aws_instance.control_plane.public_ip}:.kube/config ./kubeconfig-supermarket-assistant"
   }
   ```
6. `cd infra/terraform && terraform init`.
7. `terraform fmt -check` and `terraform validate`.
8. `terraform plan -var admin_cidr="<your-ip>/32"` — review the plan.
9. `terraform apply -var admin_cidr="<your-ip>/32"` — confirm.
10. Wait ~3–5 minutes for user-data scripts to finish. Run the `fetch_kubeconfig_command`
    output, then locally: `sed -i '' "s/127.0.0.1/$(terraform output -raw
    control_plane_public_ip)/" kubeconfig-supermarket-assistant` (adjust the sed in-place
    flag for Linux vs. macOS) so the kubeconfig points at the public IP instead of
    localhost.
11. `export KUBECONFIG=$(pwd)/kubeconfig-supermarket-assistant && kubectl get nodes` —
    confirm both nodes show `Ready` (the worker may take a minute longer to join).
12. `kubectl get pods -n kube-system` — confirm Calico and CoreDNS pods are `Running`.
13. Commit the Terraform files (not the kubeconfig or the `.pem` key — confirm `.gitignore`
    from CP1 excludes `kubeconfig*` and `*.pem`).

## Testing Tasks

- [ ] `terraform validate` and `terraform fmt -check` pass.
- [ ] `terraform plan` produces the expected resource set with no errors.
- [ ] Post-apply: `kubectl get nodes` shows 2 `Ready` nodes.
- [ ] `kubectl get pods -n kube-system` shows Calico + CoreDNS `Running`.
- [ ] Confirm the security group does **not** allow SSH/API access from `0.0.0.0/0` (only
      `admin_cidr`).

## Acceptance Criteria

From a clean AWS account with the prerequisites met, `terraform apply` produces a working
two-node kubeadm cluster reachable via `kubectl` from the developer's machine, with no
manual kubeadm commands required beyond the documented kubeconfig-fetch step.

## Risks

- Local Terraform state (no remote backend) is fine for a solo project but means state can
  be lost if the local machine is wiped — acceptable for MVP scope; note in `README.md` that
  `infra/terraform/terraform.tfstate` must not be deleted or lost between sessions.
- Kubernetes 1.30's apt repository is version-pinned deliberately (`core:/stable:/v1.30`) to
  avoid silently picking up a newer, untested minor version later.
- Cost: two `t3.medium` instances running continuously incur ongoing AWS cost — consider
  `terraform destroy` between work sessions if cost is a concern, and re-`apply` (CP10's
  ArgoCD bootstrap and `k8s/dev` state are stored in Git, so re-provisioning the cluster and
  re-running the CP10 bootstrap recovers the deployed state).

## Notes

CP11 assumes `kubectl` is already configured (via the kubeconfig fetched in step 10/11)
against this cluster before installing ArgoCD.

## Definition of Done

- [ ] All Terraform files created; `terraform apply` succeeds.
- [ ] Both nodes `Ready`, Calico/CoreDNS running, verified via `kubectl`.
- [ ] Committed with message referencing CP10 (excluding state/kubeconfig/key files).
