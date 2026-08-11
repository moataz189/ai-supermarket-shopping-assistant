# Backend image — only app/agent, app/api, app/dietary, app/metrics.py. No mcp_servers
# code (the backend only talks to MCP servers over HTTP, via app/agent/mcp_clients.py), no
# app/db (the backend never touches SQLite directly — that's supermarket-mcp's job), no
# app/ingestion.
FROM python:3.11-slim
WORKDIR /app

COPY app/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/__init__.py ./app/__init__.py
COPY app/metrics.py ./app/metrics.py
COPY app/agent ./app/agent
COPY app/api ./app/api
COPY app/dietary ./app/dietary

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# No SQLite access here, but /data still exists so the CHECKPOINTER_BACKEND=sqlite option
# (app/agent/checkpointer.py) has somewhere to write if ever enabled for this service.
RUN mkdir -p /data

CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
