#!/bin/bash
set -euo pipefail

apt-get update
apt-get install -y docker.io docker-compose-v2 nginx certbot python3-certbot-nginx

systemctl enable --now docker

mkdir -p /opt/retailer-cart-mcp/sessions/dev /opt/retailer-cart-mcp/sessions/prod
cat > /opt/retailer-cart-mcp/docker-compose.yml <<'EOF'
services:
  retailer-cart-mcp:
    image: moataz189/retailer-cart-mcp:latest
    restart: unless-stopped
    ports: ["8003:8003"]
    environment:
      PORT: "8003"
      RETAILER_SESSIONS_DIR: /app/sessions
      RETAILER_CART_MCP_API_KEY: "$${RETAILER_CART_MCP_API_KEY}"
    volumes:
      - ./sessions:/app/sessions:ro
EOF

# Real cert/nginx config wiring happens on first manual login to this box (DNS must
# already resolve to this instance's Elastic IP before certbot can validate — which it
# will, since aws_route53_record and aws_eip are created together in the same apply).
cat > /etc/nginx/sites-available/retailer-cart <<EOF
server {
    listen 80;
    server_name ${hostname};
    location / {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF
ln -sf /etc/nginx/sites-available/retailer-cart /etc/nginx/sites-enabled/retailer-cart
rm -f /etc/nginx/sites-enabled/default
systemctl reload nginx

certbot --nginx -d ${hostname} --non-interactive --agree-tos -m moataz.ody44@gmail.com --redirect
