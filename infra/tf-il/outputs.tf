output "instance_public_ip" {
  value = aws_eip.this.public_ip
}

output "ssh_private_key" {
  value     = tls_private_key.this.private_key_pem
  sensitive = true
}
