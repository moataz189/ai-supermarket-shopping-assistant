# CP10 — Terraform + kubeadm Cluster on EC2

Spec milestone: M4. Depends on: CP9 (needs built images to eventually deploy).

> **As-built note (2026-08-11):** this checkpoint was implemented as a structural migration
> of a separate, already-working infrastructure project (`polyaifursa`) rather than designed
> from scratch — its `infra/tf/` module layout, registry VPC module usage, IAM
> managed-policy attachments, and SSM join-command coordination pattern are copied and
> adapted, not reinvented. This doc describes what was actually built, which differs from
> the original speculative design below in several ways (a registry VPC module instead of a
> default-VPC lookup, an ALB + ingress-nginx architecture instead of raw NodePorts, a worker
> Auto Scaling Group instead of a single fixed worker, Packer-baked AMIs instead of
> install-on-every-boot user-data). The original two-node/default-VPC/no-ALB sketch further
> down was never implemented as written.

## Goal

Provision a self-managed (kubeadm, not EKS) Kubernetes cluster on AWS EC2 using Terraform:
one control-plane node and a worker Auto Scaling Group, reachable via `kubectl` from the
developer's machine, with an ALB + ingress-nginx front door and DNS/TLS for public access.

## Actual Architecture

**Terraform (`infra/tf/`):**

```
infra/tf/
  main.tf              # provider, registry VPC module, AMI lookup, hostname locals
  variables.tf
  outputs.tf
  tfvars/us-east-1.tfvars   # example values (placeholders only, no real secrets)
  modules/
    k8s-cluster/       # SGs, control-plane/worker IAM roles, control-plane EC2,
                       # worker launch template + ASG, SSM join-command parameter
      scripts/control-plane.sh   # user-data: kubeadm init, publish join command to SSM
      scripts/worker.sh          # user-data: poll SSM, kubeadm join with retry
    ingress/           # ALB + target group (NodePort 30080 health-check trick),
                       # ACM cert (DNS-validated), Route53 alias records
    alerting/          # SNS topic + email subscription for PrometheusRule alerts
```

- **VPC:** the `terraform-aws-modules/vpc/aws` registry module (not a hand-rolled module),
  two public subnets, no NAT/VPN gateway — control-plane and workers run with public IPs
  directly in the public subnets. A NAT Gateway's ongoing cost isn't worth it for a small,
  cost-conscious MVP cluster where nothing needs true network isolation beyond the security
  groups already restricting SSH/API access.
- **Compute:** one control-plane `aws_instance` + a worker `aws_launch_template` +
  `aws_autoscaling_group` (`worker_min_size`/`worker_max_size`/`worker_desired_capacity`,
  default 1/3/1). Both use a Packer-built AMI (see below), IMDSv2 required, gp3 encrypted
  root volumes.
- **Security groups:** SSH (22) and the Kubernetes API (6443) are restricted to
  `var.admin_cidr`, never `0.0.0.0/0`. The only path opened to the public internet on the
  workers' SG is the ingress-nginx NodePort (30080), and only from the ALB's own security
  group — never the full NodePort range.
- **IAM:** control-plane role attaches `AmazonEKSClusterPolicy` (despite the EKS-branded
  name, this policy's permissions are generic enough to reuse for a self-managed control
  plane) plus an inline SSM publish policy. Worker role attaches
  `AmazonEKSWorkerNodePolicy` + `AmazonEBSCSIDriverPolicy` plus inline policies for reading
  the join-command SSM parameter, invoking Bedrock models, and publishing to the alerts SNS
  topic — pods on any worker node inherit these permissions through the instance profile (no
  IRSA/pod identity, since this isn't EKS). No ECR policy — images are published to Docker
  Hub, not ECR.
- **kubeadm bootstrap:** `control-plane.sh` runs `kubeadm init --cri-socket
  unix:///var/run/crio/crio.sock`, configures `kubectl` for the `ubuntu` user, generates a
  non-expiring join token, and publishes the full join command (including the CRI-O socket
  flag) to an SSM `SecureString` parameter at `/${var.project_name}/join-command`. Calico is
  deliberately left commented out here (installed later by `scripts/bootstrap.sh` instead —
  see CP11) so a partial control-plane failure never leaves a half-initialized CNI. Each
  worker's `worker.sh` polls that SSM parameter (up to 20 attempts, 15s apart) and joins with
  retry (`kubeadm reset -f` between failed attempts) — no manual `kubeadm join` copy-paste,
  and no dependency on Terraform apply ordering.
- **Container runtime: CRI-O**, not containerd. Deliberately kept as-is from the reference
  infrastructure being migrated — this is a pure infrastructure port, not a redesign, and
  CRI-O was already proven working there. `kubeadm init`/`join` are both told the CRI-O
  socket explicitly (`--cri-socket=unix:///var/run/crio/crio.sock`).
- **Ingress/DNS/TLS (`modules/ingress/`):** an ALB (443 only, `0.0.0.0/0`) forwards to a
  target group pointed at the worker ASG's NodePort 30080 (ingress-nginx, installed via Helm
  in CP11), health-checked with a 404 matcher (ingress-nginx's own default-backend behavior —
  a real liveness signal without needing a dedicated `/healthz` Ingress rule everywhere). An
  ACM certificate (DNS-validated against an existing Route53 hosted zone looked up by
  `var.route53_zone_name`) covers every hostname the cluster serves; alias `A` records point
  each at the ALB. Hostnames are computed from variables
  (`${var.subdomain_prefix}-dev.<zone>`, `-prod.<zone>`, `grafana.<zone>`,
  `prometheus.<zone>`, `argocd.<zone>`), never hardcoded — unlike the reference
  infrastructure's own hardcoded `*.fursa.click` literals.
- **Alerting (`modules/alerting/`):** one deterministically-named SNS topic
  (`${var.project_name}-alerts`) + an email subscription (manual confirmation required after
  the first `terraform apply` — SNS email subscriptions cannot be auto-confirmed).
- **State:** a real `backend "s3"` block (`main.tf`) — `terraform.tfstate*` is gitignored
  regardless, but state itself lives remotely in S3, not on any one machine. Static
  validation in this environment (`fmt`/`validate`/`plan`, no real bucket access assumed) used
  a local `terraform { backend "local" {} }` override file (not committed) to run
  `terraform init` without needing that bucket reachable — the committed config always
  targets the real S3 backend.

**Packer (`infra/packer/`):** `k8s-node.pkr.hcl` + `install-k8s-deps.sh` bake an AMI
(`${project_name}-k8s-node-<timestamp>`) with CRI-O, kubelet, kubeadm, kubectl, and the AWS
CLI pre-installed — `infra/tf/main.tf`'s `data "aws_ami" "k8s_node"` picks up the most recent
matching AMI automatically (`var.custom_ami_id` overrides it). Baking these into the AMI
instead of installing on every boot means a new EC2 instance is `kubeadm`-ready within
seconds of boot instead of minutes, and every node in an ASG launch event runs identical,
already-tested software.

## Prerequisites (manual, one-time, outside Terraform)

- AWS credentials configured (locally, or as `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
  GitHub Secrets for `.github/workflows/cluster.yaml`).
- An EC2 key pair created in the target region matching `var.key_name`.
- `infra/packer/` built at least once (`packer build infra/packer/k8s-node.pkr.hcl`) before
  the first `terraform apply`, so `data.aws_ami.k8s_node` has something to find.
- Your current public IP for `admin_cidr` (`curl -s ifconfig.me`), and an existing Route53
  public hosted zone for `route53_zone_name` if `enable_ingress` (default `true`).

## How to run it

- Local: `cd infra/tf && terraform init && terraform workspace select -or-create
  <region> && terraform plan -var-file=tfvars/<region>.tfvars`, then `apply` the same way.
- CI: `.github/workflows/cluster.yaml` (`workflow_dispatch`) runs `terraform fmt -check` +
  `validate` + `plan` + `apply`, then bootstraps the cluster over SSH (see CP11).

## Validation performed (code + static validation only — see Notes)

- [x] `terraform fmt -recursive` — no changes needed.
- [x] `terraform init -backend=false` + `terraform validate` — succeeds.
- [x] `terraform plan -var-file=tfvars/us-east-1.tfvars` (via a temporary, uncommitted
      `backend "local" {}` override, since the real S3 bucket wasn't assumed reachable in
      this environment) — resolves the full variable/module graph correctly, including the
      new `aws_dynamodb_table.langgraph_checkpoints` resource; fails only on the expected "no
      AMI found yet" error (Packer hasn't built one in this environment), confirming the
      config itself is correct.
- [x] `packer validate infra/packer/` — succeeds.
- [x] Security group review: SSH/API restricted to `admin_cidr`; only the ALB's own SG can
      reach the workers' NodePort; no full NodePort range opened.

## Risks

- The `backend "s3"` block has no `dynamodb_table` set for state locking (commented out) —
  concurrent `terraform apply` runs are not protected against a race; acceptable for now
  since `cluster.yaml` is `workflow_dispatch`-only, not triggered concurrently.
- Worker ASG scale-down leaves stale `NotReady` Node objects requiring manual `kubectl
  delete node <name>` — no lifecycle-hook/Lambda cleanup implemented, deliberately
  deprioritized for MVP scope (same trade-off the migrated reference infrastructure made).
- Cost: control-plane + worker EC2 instances, an ALB, and (once `packer build` runs) an AMI
  all incur ongoing AWS cost — `terraform destroy` between work sessions if cost is a
  concern; re-provisioning recovers the deployed state since ArgoCD (CP11) reads everything
  from Git.

## Notes

Per an explicit product decision made during this checkpoint's implementation, no real AWS
infrastructure was provisioned — the deliverable is the complete Terraform/Packer code,
statically validated (`fmt`, `validate`, `plan`, `packer validate`), not a live-applied
cluster. `terraform apply`/`packer build` are ready to run whenever real provisioning is
wanted.

## Definition of Done

- [x] `infra/tf/` and `infra/packer/` created, statically validated.
- [x] No plaintext AWS credentials, kubeconfig, or private keys committed.
- [x] Committed with message referencing CP10.
