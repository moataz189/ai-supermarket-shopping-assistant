# CP9 — Containerization & Docker Compose

Spec milestone: M4 (starts). Depends on: CP5, CP7, CP8.

## Goal

Containerize the local stack — backend, all three MCP servers (each its own service), and
the React SPA — and wire it together with `docker-compose`, replacing the multi-terminal
`make run`/MCP-servers/`npm run dev` workflow used through CP8 — the last step before this
moves onto Kubernetes.

## Scope

Dockerfiles and `docker-compose.yml` only. No Kubernetes/Terraform yet (CP10–CP11).

## Key Design Decision

All three MCP servers (CP3, CP6, CP8) are long-lived **HTTP** services (spec/CP3 decision) —
unlike a stdio subprocess model, this means each one can run as its **own container**,
reachable by the backend over the docker-compose network at `http://<service-name>:<port>`.
This checkpoint uses one shared base image (`Dockerfile`) for the backend, the
Supermarket-Data MCP server, and the Recipe MCP server — each just runs a different
`command:` — and a **separate** image (`Dockerfile.retailer-cart-mcp`) for the Retailer-Cart
MCP server, since it alone needs Playwright's browser binaries and there's no reason to bloat
the other three images with them.

## Deliverables

- `docker compose up` starts all four backend-side services (backend, supermarket-mcp,
  recipe-mcp, retailer-cart-mcp) plus the web UI, fully replicating the CP8 manually-run
  setup — including choosing a retailer and seeing Playwright prepare its cart against the
  mock retailer site.
- `docker compose --profile tools run ingestion` runs the ingestion CLI inside a container.

## Files to Create

```
Dockerfile
Dockerfile.retailer-cart-mcp
web/Dockerfile
web/nginx.conf
docker-compose.yml
scripts/smoke_test.sh
```

## Detailed Implementation Steps

1. Write `Dockerfile` (shared base for backend/supermarket-mcp/recipe-mcp — no Playwright).
   Only `requirements.txt` is installed — never `requirements-dev.txt` — so production
   images stay free of pytest/ruff/flask/pytest-playwright:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app

   COPY requirements.txt ./
   RUN pip install --no-cache-dir -r requirements.txt

   COPY app ./app
   COPY mcp_servers ./mcp_servers

   ENV PYTHONUNBUFFERED=1
   EXPOSE 8000

   CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
   (`python -m uvicorn`, not a bare `uvicorn`, for the same reason as CP1's `make run` —
   guarantees `/app` is on `sys.path` without installing the local code as a package.
   Installing `requirements.txt` before copying `app`/`mcp_servers` lets Docker cache the
   dependency layer across builds where only application code changed. The default `CMD` is
   the backend's; `supermarket-mcp`/`recipe-mcp` override it via `command:` in
   `docker-compose.yml`, step 4.)
2. Write `Dockerfile.retailer-cart-mcp`:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app

   COPY requirements.txt ./
   RUN pip install --no-cache-dir -r requirements.txt
   RUN playwright install --with-deps chromium

   COPY app ./app
   COPY mcp_servers ./mcp_servers

   ENV PYTHONUNBUFFERED=1
   EXPOSE 8003

   CMD ["python", "-m", "mcp_servers.retailer_cart_mcp.server"]
   ```
3. Write `web/Dockerfile` (multi-stage: build the static SPA, serve with nginx):
   ```dockerfile
   FROM node:20-slim AS build
   WORKDIR /web
   COPY web/package.json web/package-lock.json ./
   RUN npm ci
   COPY web ./
   RUN npm run build

   FROM nginx:1.27-alpine
   COPY --from=build /web/dist /usr/share/nginx/html
   COPY web/nginx.conf /etc/nginx/conf.d/default.conf
   EXPOSE 80
   ```
4. Write `web/nginx.conf` (proxy `/api/` to the backend so the SPA needs no CORS config):
   ```nginx
   server {
     listen 80;
     location /api/ {
       proxy_pass http://backend:8000/;
     }
     location / {
       root /usr/share/nginx/html;
       try_files $uri /index.html;
     }
   }
   ```
5. Write `docker-compose.yml` — four backend-side services, each its own container, the
   backend wired to the other three by URL:
   ```yaml
   services:
     supermarket-mcp:
       build: { context: ., dockerfile: Dockerfile }
       command: ["python", "-m", "mcp_servers.supermarket_mcp.server"]
       environment:
         DATABASE_URL: sqlite:///./app.db
         PORT: "8001"
       volumes:
         - backend_data:/app
       ports: ["8001:8001"]

     recipe-mcp:
       build: { context: ., dockerfile: Dockerfile }
       command: ["python", "-m", "mcp_servers.recipe_mcp.server"]
       environment:
         SPOONACULAR_API_KEY: ${SPOONACULAR_API_KEY}
         PORT: "8002"
       ports: ["8002:8002"]

     retailer-cart-mcp:
       build: { context: ., dockerfile: Dockerfile.retailer-cart-mcp }
       environment:
         PORT: "8003"
         RETAILER_SESSIONS_DIR: /app/sessions
       volumes:
         - ./sessions:/app/sessions:ro
       ports: ["8003:8003"]

     backend:
       build: { context: ., dockerfile: Dockerfile }
       environment:
         DATABASE_URL: sqlite:///./app.db
         CHECKPOINTER_BACKEND: memory
         BEDROCK_MODEL_ID: ${BEDROCK_MODEL_ID}
         AWS_REGION: ${AWS_REGION:-us-east-1}
         SUPERMARKET_MCP_URL: http://supermarket-mcp:8001/mcp
         RECIPE_MCP_URL: http://recipe-mcp:8002/mcp
         RETAILER_CART_MCP_URL: http://retailer-cart-mcp:8003/mcp
       ports: ["8000:8000"]
       volumes:
         - backend_data:/app
         - ${HOME}/.aws:/root/.aws:ro
       depends_on: [supermarket-mcp, recipe-mcp, retailer-cart-mcp]

     web:
       build: { context: ., dockerfile: web/Dockerfile }
       ports: ["5173:80"]
       depends_on: [backend]

     ingestion:
       build: { context: ., dockerfile: Dockerfile }
       command: ["python", "-m", "app.ingestion.run", "--source", "fixtures"]
       environment:
         DATABASE_URL: sqlite:///./app.db
       volumes:
         - backend_data:/app
       profiles: ["tools"]

   volumes:
     backend_data:
   ```
   (`${HOME}/.aws:/root/.aws:ro` lets the backend container use the developer's local AWS
   credentials for real Bedrock calls during manual testing. MCP server ports are published
   to the host mainly for local debugging — the backend reaches them via the compose network
   regardless.)
6. Write `scripts/smoke_test.sh`:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail

   docker compose up -d --build
   trap 'docker compose down' EXIT

   for i in {1..30}; do
     if curl -sf localhost:8000/health > /dev/null; then
       echo "backend healthy"
       break
     fi
     sleep 1
   done
   curl -sf localhost:8000/health
   curl -sf localhost:5173/ > /dev/null
   echo "smoke test passed"
   ```
   `chmod +x scripts/smoke_test.sh`.
7. Run `docker compose build`, fix any image build errors (missing files, dependency
   resolution, Playwright install failures in `Dockerfile.retailer-cart-mcp`).
8. Run `./scripts/smoke_test.sh` and confirm it exits 0.
9. Manually open `localhost:5173`, run through the flows verified in CP5/CP7: grocery list
   happy path (both carts), ambiguous clarification, recipe request. Then exercise the
   `retailer-cart-mcp` container itself: with `./sessions/` empty, choose a retailer and
   confirm the UI shows a graceful `login_required` result (no crash); then, if you want to
   verify a real end-to-end add, run CP8's `login.py` **locally on the host** (not in a
   container — it needs a real display) for one retailer, confirm it wrote
   `sessions/<retailer>.json`, and re-run the flow to see Playwright actually add items to
   that retailer's real cart. (CP8's mock-site automation tests already cover the detailed
   add/fail/block behavior — this step is about confirming the container wiring, not
   re-testing that logic.)
10. Run `docker compose --profile tools run --rm ingestion` and confirm it completes and
    populates the shared `backend_data` volume's SQLite file.
11. Commit.

## Testing Tasks

- [ ] `scripts/smoke_test.sh` passes (backend `/health` and web root both reachable).
- [ ] Manual walkthrough of grocery-list, clarification, recipe, and retailer-choice/
      Playwright flows against the containerized stack.
- [ ] `docker compose --profile tools run ingestion` completes successfully.
- [ ] Stopping `retailer-cart-mcp` (or `supermarket-mcp`) and retrying a request surfaces a
      clear error rather than hanging — confirms the backend actually depends on these
      services being up, not silently falling back to something else.

## Acceptance Criteria

A developer with only Docker installed (no local Python/Node toolchain) can run
`docker compose up` and use the full chat UI locally — including choosing a retailer and
seeing Playwright prepare its cart against the mock retailer site — identical in behavior to
the CP8 manually-run setup.

## Risks

- Four backend-side containers (vs. one bundled image) is more moving parts locally —
  acceptable trade-off for matching how this will actually run in Kubernetes (CP11), where
  each MCP server is its own Deployment/Service anyway.
- `Dockerfile.retailer-cart-mcp`'s `playwright install --with-deps` meaningfully increases
  that one image's size — acceptable since it's isolated from the other three images now.
- `./sessions/` is a local host directory mounted read-only into `retailer-cart-mcp` — it
  must exist (even empty) before `docker compose up`, and must never be committed (CP8's
  `.gitignore` entry covers this).

## Notes

CP10/CP11 build `k8s/dev` Deployments from these same two Dockerfiles (one per MCP server
plus the backend, all from `Dockerfile`; `retailer-cart-mcp` from its own) — keep both
images self-contained (no host-path dependencies beyond environment variables and the
optional local AWS credentials mount).

## Definition of Done

- [ ] Both Dockerfiles, the web Dockerfile/nginx config, compose file, and smoke test script
      created.
- [ ] Smoke test passes; manual walkthrough confirms parity with CP8.
- [ ] Committed with message referencing CP9.
