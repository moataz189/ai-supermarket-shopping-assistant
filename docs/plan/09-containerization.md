# CP9 — Containerization & Docker Compose

Spec milestone: M4 (starts). Depends on: CP5, CP7, CP8.

## Goal

Containerize the whole local stack (backend + agent + all three MCP servers, ingestion job,
React SPA) and wire it together with `docker-compose`, replacing the multi-terminal
`make run` / `npm run dev` workflow used through CP8 — the last step before this moves onto
Kubernetes.

## Scope

Dockerfiles and `docker-compose.yml` only. No Kubernetes/Terraform yet (CP10–CP11).

## Key Design Decision

The Recipe, Supermarket-Data, and Retailer-Cart MCP servers (CP3, CP6, CP8) are invoked over
**stdio** by their respective client classes (CP4/CP7/CP8), which spawn them as
**subprocesses**. That only works if all three MCP server modules are present in the *same
container* as the backend process. This checkpoint therefore builds **one backend image**
containing `app/` and `mcp_servers/` together — it does not split the MCP servers into their
own containers. This satisfies the spec's requirement to have real, custom MCP servers; it
does not require them to be separately deployed network services.

The Retailer-Cart MCP server (CP8) depends on Playwright's browser binaries, which must be
installed into this same backend image (see step 1) — otherwise browser automation would
fail at runtime inside the container even though it works on a developer's machine.

## Deliverables

- `docker compose up` serves the backend on `localhost:8000` and the web UI on
  `localhost:5173`, fully replicating the CP8 manual-run setup — including a working
  cart-approval → Playwright cart-preparation flow against the CP8 mock retailer site.
- `docker compose --profile tools run ingestion` runs the ingestion CLI inside a container.

## Files to Create

```
Dockerfile.backend
web/Dockerfile
web/nginx.conf
docker-compose.yml
scripts/smoke_test.sh
```

## Detailed Implementation Steps

1. Write `Dockerfile.backend`, including the Playwright browser install step required by
   the Retailer-Cart MCP server (CP8):
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app

   COPY pyproject.toml ./
   COPY app ./app
   COPY mcp_servers ./mcp_servers

   RUN pip install --no-cache-dir .
   RUN playwright install --with-deps chromium

   ENV PYTHONUNBUFFERED=1
   EXPOSE 8000

   CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
2. Write `web/Dockerfile` (multi-stage: build the static SPA, serve with nginx):
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
3. Write `web/nginx.conf`, proxying `/api/` to the backend service so the SPA's
   `fetch("/api/chat")` calls work without CORS configuration:
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
4. Write `docker-compose.yml`, including the Retailer-Cart MCP server's environment (the
   mock-site URL is only used in tests, not here; production/dev site URLs are looked up
   internally by the retailer adapters from CP8, not passed as compose env vars):
   ```yaml
   services:
     backend:
       build:
         context: .
         dockerfile: Dockerfile.backend
       environment:
         DATABASE_URL: sqlite:///./app.db
         CHECKPOINTER_BACKEND: memory
         BEDROCK_MODEL_ID: ${BEDROCK_MODEL_ID}
         AWS_REGION: ${AWS_REGION:-us-east-1}
         SPOONACULAR_API_KEY: ${SPOONACULAR_API_KEY}
       ports:
         - "8000:8000"
       volumes:
         - backend_data:/app
         - ${HOME}/.aws:/root/.aws:ro

     web:
       build:
         context: .
         dockerfile: web/Dockerfile
       ports:
         - "5173:80"
       depends_on:
         - backend

     ingestion:
       build:
         context: .
         dockerfile: Dockerfile.backend
       command: ["python", "-m", "app.ingestion.run", "--source", "fixtures"]
       environment:
         DATABASE_URL: sqlite:///./app.db
       volumes:
         - backend_data:/app
       profiles: ["tools"]

   volumes:
     backend_data:
   ```
   (The `${HOME}/.aws:/root/.aws:ro` mount lets the backend container use the developer's
   local AWS credentials for real Bedrock calls during manual testing.)
5. Write `scripts/smoke_test.sh`:
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
6. Run `docker compose build`, fix any image build errors (missing files in build context,
   dependency resolution issues, Playwright browser install failures — `playwright install
   --with-deps` needs the container's apt package manager available, which the
   `python:3.11-slim` base image has).
7. Run `./scripts/smoke_test.sh` and confirm it exits 0.
8. Manually open `localhost:5173`, run through the flows verified in CP5/CP7/CP8 (grocery
   list happy path, ambiguous clarification, recipe request, and — using CP8's mock retailer
   site running locally — the cart-approval-then-Playwright-preparation flow) against the
   containerized stack.
9. Run `docker compose --profile tools run --rm ingestion` and confirm it completes and
   populates the shared `backend_data` volume's SQLite file.
10. Commit.

## Testing Tasks

- [ ] `scripts/smoke_test.sh` passes (backend `/health` and web root both reachable).
- [ ] Manual walkthrough of grocery-list, clarification, recipe, and cart-approval/Playwright
      flows against the containerized stack.
- [ ] `docker compose --profile tools run ingestion` completes successfully.

## Acceptance Criteria

A developer with only Docker installed (no local Python/Node toolchain) can run
`docker compose up` and use the full chat UI locally — including approving a cart and seeing
Playwright prepare it against the mock retailer site — identical in behavior to the CP8
manually-run setup.

## Risks

- Bundling all three MCP servers into the backend image (rather than separate services)
  means a bug in one MCP server's startup can affect the whole backend process — acceptable
  trade-off for MVP scope per the Key Design Decision above; revisit only if a real
  operational problem appears.
- `playwright install --with-deps chromium` meaningfully increases the backend image size —
  acceptable for MVP; a future optimization could split the Retailer-Cart MCP server into
  its own image if this becomes a real deployment concern.

## Notes

CP10/CP11 will build a `k8s/dev` Deployment from this same `Dockerfile.backend` image, so
keep the image self-contained (no host-path dependencies beyond environment variables and
the optional AWS credentials mount used only for local dev).

## Definition of Done

- [ ] All three Dockerfiles/compose file/smoke test script created, including the Playwright
      browser install step.
- [ ] Smoke test passes; manual walkthrough confirms parity with CP8.
- [ ] Committed with message referencing CP9.
