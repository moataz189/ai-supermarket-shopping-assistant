# Recipe MCP image — only mcp_servers/recipe_mcp. No supermarket/DB code, no Playwright.
FROM python:3.11-slim
WORKDIR /app

COPY mcp_servers/recipe_mcp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_servers/recipe_mcp ./mcp_servers/recipe_mcp

ENV PYTHONUNBUFFERED=1
EXPOSE 8002

CMD ["python", "-m", "mcp_servers.recipe_mcp.server"]
