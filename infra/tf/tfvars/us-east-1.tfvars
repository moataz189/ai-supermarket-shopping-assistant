# Copy this file (or add a *.auto.tfvars alongside it, gitignored) to layer in the
# secrets below rather than editing this tracked file — admin_cidr and alert_email
# especially should not be committed with real values.

region       = "us-east-1"
project_name = "supermarket-assistant"

# Required — no safe default. Get yours with: curl -s ifconfig.me
admin_cidr = "203.0.113.4/32"

key_name = "supermarket-assistant"

worker_min_size         = 1
worker_max_size         = 3
worker_desired_capacity = 1

# Required when enable_ingress = true (the default) — an existing Route53 public hosted
# zone this AWS account already manages. Leave enable_ingress = false (and this blank) to
# provision just the cluster without DNS/ALB/ACM.
route53_zone_name = "fursa.click"
subdomain_prefix  = "supermarket"

# Required — subscribes this address to the alerts SNS topic (confirmation email sent on
# first apply).
alert_email = "moataz.ody44@gmail.com"
custom_ami_id = "ami-07fc2802e9e3091be"