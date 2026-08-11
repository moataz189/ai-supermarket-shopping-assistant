# A deterministic name (no random suffix) so the topic ARN stays stable across
# destroy/re-apply cycles — Alertmanager's Helm values
# (infra/k8s/monitoring/values.yaml.tpl) reference this ARN, rendered once by CI after
# `terraform apply` and committed back to git; a stable ARN means that render step only
# needs to run again when the ARN actually changes, not on every apply.
resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
