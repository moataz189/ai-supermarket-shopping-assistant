data "aws_route53_zone" "this" {
  name         = var.route53_zone_name
  private_zone = false
}

# ALB/target-group names are capped at 32 chars by AWS — truncate defensively.
locals {
  short_name_prefix = substr(var.project_name, 0, 20)
}

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb-sg"
  description = "Public ALB, HTTPS only"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.project_name}-alb-sg" })
}

# The only path opened on the workers' security group to the public internet — scoped to
# traffic from the ALB's own security group, on exactly the ingress-nginx NodePort, never
# the full NodePort range and never 0.0.0.0/0 directly.
resource "aws_security_group_rule" "workers_from_alb_node_port" {
  type                     = "ingress"
  from_port                = var.worker_node_port
  to_port                  = var.worker_node_port
  protocol                 = "tcp"
  security_group_id        = var.worker_security_group_id
  source_security_group_id = aws_security_group.alb.id
  description              = "ALB to ingress-nginx NodePort"
}

resource "aws_acm_certificate" "this" {
  domain_name               = var.hostnames[0]
  subject_alternative_names = slice(var.hostnames, 1, length(var.hostnames))
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(var.tags, { Name = "${var.project_name}-cert" })
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.this.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = data.aws_route53_zone.this.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

resource "aws_lb" "this" {
  name               = "${local.short_name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.subnet_ids

  tags = merge(var.tags, { Name = "${var.project_name}-alb" })
}

resource "aws_lb_target_group" "http_node_port" {
  name        = "${local.short_name_prefix}-ingress-tg"
  port        = var.worker_node_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "instance"

  health_check {
    protocol = "HTTP"
    path     = "/"
    # ingress-nginx's default backend answers 404 for any request that doesn't match a
    # configured Ingress host — a real "I am alive" signal from a health-check request
    # that will never itself match a real Ingress rule, without a dedicated /healthz path
    # wired through every Ingress.
    matcher             = "404"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
  }

  tags = merge(var.tags, { Name = "${var.project_name}-ingress-tg" })
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.this.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.http_node_port.arn
  }
}

resource "aws_autoscaling_attachment" "workers" {
  autoscaling_group_name = var.worker_asg_name
  lb_target_group_arn    = aws_lb_target_group.http_node_port.arn
}

resource "aws_route53_record" "alb_alias" {
  for_each = toset(var.hostnames)

  zone_id = data.aws_route53_zone.this.zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}
