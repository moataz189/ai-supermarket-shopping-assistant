output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "alb_zone_id" {
  value = aws_lb.this.zone_id
}

output "certificate_arn" {
  value = aws_acm_certificate_validation.this.certificate_arn
}

output "hostnames" {
  value = var.hostnames
}
