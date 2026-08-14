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

cat > /etc/nginx/sites-available/retailer-cart <<EOF
server {
    listen 80;
    server_name ${hostname};
    location / {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;

        # nginx's default proxy_read_timeout (60s) is too short for a real Playwright
        # cart run against a retailer's live site — see web/nginx.conf's own fix for the
        # same failure mode on the backend proxy. proxy_connect_timeout stays short since
        # connecting to 127.0.0.1:8003 is near-instant. 300s (not 180s) confirmed live:
        # an 8-item Rami Levy cart still 504'd at 180s end-to-end (this instance was not
        # the confirmed bottleneck, but every hop in the chain must tolerate the same
        # ceiling) — matches the MCP client's own existing sse_read_timeout default
        # (mcp/client/streamable_http.py, 60*5s), the true end-to-end ceiling.
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        # MCP's streamable-HTTP/SSE connection needs these in addition to the timeouts
        # above: buffering off so events stream through as they arrive instead of being
        # queued up by nginx, and an empty Connection header so nginx doesn't force
        # "close" on what needs to stay a long-lived connection.
        proxy_buffering off;
        proxy_set_header Connection "";
    }
}
EOF
ln -sf /etc/nginx/sites-available/retailer-cart /etc/nginx/sites-enabled/retailer-cart
rm -f /etc/nginx/sites-enabled/default
systemctl reload nginx

# TLS is deliberately NOT set up here: certbot's HTTP-01 challenge needs DNS already
# resolving to this instance's Elastic IP, but at boot time the EIP association and
# Route53 record from this same `terraform apply` may not have propagated yet. TLS is
# set up manually — a human runs `certbot --nginx -d ${hostname} ...` by hand on the
# instance after `terraform apply` completes and DNS has had time to propagate.
