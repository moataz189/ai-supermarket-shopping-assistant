# Retailer-Cart MCP image — only mcp_servers/retailer_cart_mcp. No supermarket/recipe MCP
# code. The only image of the five that installs Playwright's browser binaries.
#
# Runs as root: sessions/<retailer>.json is bind-mounted read-only from the host at
# restrictive 0600 permissions captured by CP8's login.py, and a non-root container uid is
# not guaranteed to match the host uid that owns those files (especially under Docker
# Desktop's bind-mount uid mapping) — running as a mismatched non-root user would silently
# break session loading. The mount is read-only regardless, so root here cannot modify or
# exfiltrate the session files any more than a non-root user could.
FROM python:3.11-slim
WORKDIR /app

COPY mcp_servers/retailer_cart_mcp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

COPY mcp_servers/retailer_cart_mcp ./mcp_servers/retailer_cart_mcp

ENV PYTHONUNBUFFERED=1
EXPOSE 8003

CMD ["python", "-m", "mcp_servers.retailer_cart_mcp.server"]
