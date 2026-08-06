# Supermarket-Data MCP image — only mcp_servers/supermarket_mcp + app/db (the SQLite
# access layer it needs). No Recipe MCP or Retailer-Cart MCP code, no backend/agent code.
FROM python:3.11-slim
WORKDIR /app

COPY mcp_servers/supermarket_mcp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/__init__.py ./app/__init__.py
COPY app/db ./app/db
COPY mcp_servers/supermarket_mcp ./mcp_servers/supermarket_mcp

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

# Persistent SQLite data lives under /data (compose mounts a named volume there) — kept
# separate from /app so a data volume mount never hides the application code copied above.
RUN mkdir -p /data

CMD ["python", "-m", "mcp_servers.supermarket_mcp.server"]
