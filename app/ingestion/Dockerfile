# Ingestion image — only app/ingestion + app/db + the feed fixtures it loads. No
# mcp_servers code, no FastAPI/agent code. One-shot CLI, runs under the `tools` compose
# profile only (docker-compose.yml), never part of the always-on service set.
FROM python:3.11-slim
WORKDIR /app

COPY app/ingestion/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/__init__.py ./app/__init__.py
COPY app/db ./app/db
COPY app/ingestion ./app/ingestion
# `python -m app.ingestion.run --source fixtures` reads these at runtime; only the feed
# fixtures are copied, not the whole test suite.
COPY tests/fixtures/feeds ./tests/fixtures/feeds

ENV PYTHONUNBUFFERED=1

# Persistent SQLite data lives under /data (compose mounts the same named volume as
# backend/supermarket-mcp there) — kept separate from /app so the volume mount never hides
# the application code copied above.
RUN mkdir -p /data

CMD ["python", "-m", "app.ingestion.run", "--source", "fixtures"]
