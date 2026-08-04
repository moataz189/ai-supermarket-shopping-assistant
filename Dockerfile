# Shared image for: backend, supermarket-mcp, recipe-mcp, ingestion (each just runs a
# different `command:` in docker-compose.yml). Deliberately does NOT install Playwright's
# browser binaries — only mcp_servers/retailer_cart_mcp needs those, see
# Dockerfile.retailer-cart-mcp. Only requirements.txt is installed — never
# requirements-dev.txt — so this image stays free of pytest/ruff/pytest-playwright/flask.
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY mcp_servers ./mcp_servers
# Ingestion's fixtures-source mode (`--source fixtures`) reads these at runtime; only the
# feed fixtures are copied, not the whole test suite (spoonacular fixtures etc. are unused
# by ingestion and stay out of the image).
COPY tests/fixtures/feeds ./tests/fixtures/feeds

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Persistent SQLite data lives under /data (compose mounts a named volume there) — kept
# separate from /app so a data volume mount never hides the application code copied above.
RUN mkdir -p /data

# Runs as root: the backend service also bind-mounts the developer's ${HOME}/.aws read-only
# for local Bedrock calls (docker-compose.yml) — a non-root container uid is not guaranteed
# to match the host uid Docker Desktop presents for that mount, which would silently break
# credential loading; root reads it regardless. Revisited for Kubernetes (CP10/11), which
# uses IAM/Secret-based credential delivery instead of a host bind-mount.

# `python -m uvicorn`, not a bare `uvicorn`, guarantees /app is on sys.path without
# installing the local code as a package. The default CMD is the backend's;
# supermarket-mcp/recipe-mcp/ingestion override it via `command:` in docker-compose.yml.
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
