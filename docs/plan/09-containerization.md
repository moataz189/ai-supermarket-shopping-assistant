# CP9 — Containerization & Docker Compose

Spec milestone: M4 (starts). Depends on: CP5, CP7, CP8.

> **Revision note:** this plan was corrected after initial implementation and live
> verification against the real Docker Compose stack (real Bedrock, real Shufersal/Rami
> Levy adapters, real captured sessions). The original draft's acceptance criteria
> incorrectly implied normal `docker compose up` runs against the mock retailer site — see
> "Real runtime vs. test-only mock site" below. All corrections found necessary during
> implementation are documented inline and in **Notes**.

## Goal

Containerize the local stack — backend, all three MCP servers (each its own service), and
the React SPA — and wire it together with `docker-compose`, replacing the multi-terminal
`make run`/MCP-servers/`npm run dev` workflow used through CP8 — the last step before this
moves onto Kubernetes. The normal Compose runtime uses the **real** FastAPI backend, real
Supermarket/Recipe/Retailer-Cart MCP servers, real ShufersalAdapter/RamiLevyAdapter, real
Spoonacular API (when configured), and real Bedrock model (when configured) — not the mock
retailer site used by CP8's automated tests.

## Scope

Dockerfiles and `docker-compose.yml` only. No Kubernetes/Terraform yet (CP10–CP11).

## Key Design Decision

All three MCP servers (CP3, CP6, CP8) are long-lived **HTTP** services (spec/CP3 decision) —
unlike a stdio subprocess model, this means each one can run as its **own container**,
reachable by the backend over the docker-compose network at `http://<service-name>:<port>`.
This checkpoint uses one shared base image (`Dockerfile`) for the backend, the
Supermarket-Data MCP server, the Recipe MCP server, and the ingestion CLI — each just runs a
different `command:` — and a **separate** image (`Dockerfile.retailer-cart-mcp`) for the
Retailer-Cart MCP server, since it alone needs Playwright's browser binaries and there's no
reason to bloat the other images with them.

## Real runtime vs. test-only mock site

CP8's mock retailer site (`tests/mcp/mock_site_server.py`) is exercised only by
`pytest`/CI — it is **never** part of the `docker-compose.yml` service list. Normal
`docker compose up` always uses the real `ShufersalAdapter`/`RamiLevyAdapter` against the
real `shufersal.co.il`/`rami-levy.co.il` sites, gated on a previously-captured login session
under `./sessions/` (CP8's `login.py`, run manually on the host, never in a container).
Choosing a retailer with no valid session returns a graceful `login_required` result; the
automation never logs in itself and never reaches checkout/payment.

## Deliverables

- `docker compose up` starts all four backend-side services (backend, supermarket-mcp,
  recipe-mcp, retailer-cart-mcp) plus the web UI, using the **real** application flow
  end-to-end (real Bedrock, real MCP servers, real retailer adapters).
- `docker compose --profile tools run ingestion` runs the ingestion CLI inside a container,
  populating a SQLite database under a dedicated `/data` volume shared with `backend` and
  `supermarket-mcp`.
- `scripts/smoke_test.sh` proves container construction and basic reachability (build, up,
  health-checked readiness, teardown) without requiring real external API calls.
- `.env.example` / `.env` documenting all runtime configuration.
- `.dockerignore` keeping secrets, sessions, and dev-only artifacts out of every image.

## Files to Create

```
Dockerfile
Dockerfile.retailer-cart-mcp
web/Dockerfile
web/nginx.conf
docker-compose.yml
scripts/smoke_test.sh
.dockerignore
.env.example
.env (gitignored)
```

## Detailed Implementation Steps

1. Write `Dockerfile` (shared image for backend/supermarket-mcp/recipe-mcp/ingestion — no
   Playwright). Only `requirements.txt` is installed — never `requirements-dev.txt` — so
   this image stays free of pytest/ruff/flask/pytest-playwright:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app

   COPY requirements.txt ./
   RUN pip install --no-cache-dir -r requirements.txt

   COPY app ./app
   COPY mcp_servers ./mcp_servers
   COPY tests/fixtures/feeds ./tests/fixtures/feeds

   ENV PYTHONUNBUFFERED=1
   EXPOSE 8000

   RUN mkdir -p /data

   CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
   Corrections from the original draft:
   - **`tests/fixtures/feeds` is copied into the image** (only the feed fixtures, not the
     whole test suite) — `app.ingestion.run --source fixtures` reads them at runtime, and
     without this the `ingestion` service (which reuses this same image) would fail with a
     missing-file error. See step 8.
   - **`/data` is a plain directory, not a volume target for `/app`.** The original draft
     mounted `backend_data:/app`, which would hide the application code `COPY`'d into the
     image at container start — a named volume mount point is empty on first use and
     shadows whatever the image put there. `DATABASE_URL` now points at
     `sqlite:////data/app.db` (four slashes: `sqlite://` + absolute path `/data/app.db`),
     and only `/data` is volume-mounted (step 5).
   - **Runs as root**, not a hardened non-root user. `backend` also bind-mounts the
     developer's `${HOME}/.aws` read-only for local Bedrock calls (step 5) — those
     credential files are typically `0600`, and a non-root container uid is not guaranteed
     to match the host uid Docker Desktop presents for that bind mount, which would
     silently break credential loading. Root reads it regardless (Linux DAC override).
     Revisited for Kubernetes (CP10/11), which uses IAM-role/Secret-based credential
     delivery instead of a host bind-mount, where non-root becomes safe.
2. Write `Dockerfile.retailer-cart-mcp`:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app

   COPY requirements.txt ./
   RUN pip install --no-cache-dir -r requirements.txt
   RUN python -m playwright install --with-deps chromium

   COPY mcp_servers ./mcp_servers

   ENV PYTHONUNBUFFERED=1
   EXPOSE 8003

   CMD ["python", "-m", "mcp_servers.retailer_cart_mcp.server"]
   ```
   Corrections: no `COPY app ./app` — `mcp_servers/retailer_cart_mcp` has no dependency on
   the `app` package, so it's left out to keep this image's scope minimal. Also runs as
   root, for the same reason as the shared image: `./sessions/` is bind-mounted read-only
   at restrictive `0600` permissions (CP8's `login.py`), and a non-root container uid isn't
   guaranteed to match the host uid — root reads it regardless, and the mount is read-only
   so root here can't modify or exfiltrate session files any more than a non-root user
   could.
3. Write `web/Dockerfile` (multi-stage: build the static SPA, serve with nginx) — unchanged
   from the original draft:
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
   **Correction found during `docker compose build`:** `web/package-lock.json` was out of
   sync with `package.json` (missing an optional `@emnapi/runtime` entry transitively
   required by Tailwind v4's oxide/wasm optional deps), so `npm ci` failed outright.
   Regenerated with `docker run --rm -v "$PWD/web:/web" -w /web node:20-slim npm install
   --package-lock-only` (using the same Node major version as the build image, not the
   host's) and committed the corrected lockfile — unrelated to containerization logic
   itself, but `npm ci`'s strictness surfaced a pre-existing drift.
4. Write `web/nginx.conf` (serve the SPA with an `index.html` fallback; proxy `/api/` to the
   backend, preserving normal proxy headers so the SPA needs no CORS config):
   ```nginx
   server {
     listen 80;

     location /api/ {
       proxy_pass http://backend:8000/;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
     }

     location / {
       root /usr/share/nginx/html;
       try_files $uri /index.html;
     }
   }
   ```
5. Write `docker-compose.yml` — four backend-side services, each its own container, the
   backend wired to the other three by URL, plus `web` and the `tools`-profile `ingestion`
   service. Key corrections from the original draft, found during live verification:
   - **`/data` volumes, not `/app`** — `backend`, `supermarket-mcp`, and `ingestion` mount
     `backend_data:/data` and set `DATABASE_URL: sqlite:////data/app.db`; `recipe-mcp` and
     `retailer-cart-mcp` don't touch the database at all, so they get no data volume.
   - **Health-aware `depends_on`** — `backend` waits on `supermarket-mcp`, `recipe-mcp`,
     and `retailer-cart-mcp` with `condition: service_healthy`; `web` waits on `backend`
     the same way. See step 7.
   - **Healthchecks use `127.0.0.1`, not `localhost`.** The nginx (`web`) container's
     Alpine/musl `wget` resolves `localhost` to `::1` (IPv6) first and nginx only listens
     on IPv4 by default, so `wget --spider http://localhost/` flapped the container
     `unhealthy` even though the service worked fine (confirmed via `docker inspect`'s
     health-check log and a working `curl localhost:5173` from the host). Using
     `127.0.0.1` explicitly in every service's healthcheck avoids relying on
     hosts-resolution order/address-family preference at all.
   - **`RETAILER_SESSIONS_DIR=/app/sessions`** with `./sessions:/app/sessions:ro` — real
     captured session files, read-only, never copied into any image.
   - **`${HOME}/.aws:/root/.aws:ro`** on `backend` only, documented as local-development-only
     (see step 9).
   - Ports match the original draft: web `5173:80`, backend `8000:8000`, supermarket-mcp
     `8001:8001`, recipe-mcp `8002:8002`, retailer-cart-mcp `8003:8003`.
   ```yaml
   services:
     supermarket-mcp:
       build: { context: ., dockerfile: Dockerfile }
       command: ["python", "-m", "mcp_servers.supermarket_mcp.server"]
       environment:
         DATABASE_URL: sqlite:////data/app.db
         PORT: "8001"
       volumes: [ "backend_data:/data" ]
       ports: ["8001:8001"]
       healthcheck:
         test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"]
         interval: 5s
         timeout: 3s
         retries: 10
         start_period: 5s

     recipe-mcp:
       build: { context: ., dockerfile: Dockerfile }
       command: ["python", "-m", "mcp_servers.recipe_mcp.server"]
       environment:
         SPOONACULAR_API_KEY: ${SPOONACULAR_API_KEY}
         PORT: "8002"
       ports: ["8002:8002"]
       healthcheck: # same python-urllib pattern against :8002/health

     retailer-cart-mcp:
       build: { context: ., dockerfile: Dockerfile.retailer-cart-mcp }
       environment:
         PORT: "8003"
         RETAILER_SESSIONS_DIR: /app/sessions
       volumes: [ "./sessions:/app/sessions:ro" ]
       ports: ["8003:8003"]
       healthcheck: # same python-urllib pattern against :8003/health

     backend:
       build: { context: ., dockerfile: Dockerfile }
       environment:
         DATABASE_URL: sqlite:////data/app.db
         CHECKPOINTER_BACKEND: memory
         BEDROCK_MODEL_ID: ${BEDROCK_MODEL_ID}
         AWS_REGION: ${AWS_REGION:-us-east-1}
         SUPERMARKET_MCP_URL: http://supermarket-mcp:8001/mcp
         RECIPE_MCP_URL: http://recipe-mcp:8002/mcp
         RETAILER_CART_MCP_URL: http://retailer-cart-mcp:8003/mcp
       ports: ["8000:8000"]
       volumes:
         - backend_data:/data
         - ${HOME}/.aws:/root/.aws:ro   # local dev only — see step 9
       depends_on:
         supermarket-mcp: { condition: service_healthy }
         recipe-mcp: { condition: service_healthy }
         retailer-cart-mcp: { condition: service_healthy }
       healthcheck: # python-urllib against :8000/health

     web:
       build: { context: ., dockerfile: web/Dockerfile }
       ports: ["5173:80"]
       depends_on:
         backend: { condition: service_healthy }
       healthcheck:
         test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://127.0.0.1/"]
         interval: 5s
         timeout: 3s
         retries: 10
         start_period: 5s

     ingestion:
       build: { context: ., dockerfile: Dockerfile }
       command: ["python", "-m", "app.ingestion.run", "--source", "fixtures"]
       environment:
         DATABASE_URL: sqlite:////data/app.db
       volumes: [ "backend_data:/data" ]
       profiles: ["tools"]

   volumes:
     backend_data:
   ```
6. Write `.dockerignore` (new — not in the original draft): excludes `.git/`,
   `.worktrees/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, coverage
   artifacts, `*.db`, `.env*` (except `.env.example`), `sessions/`, `web/node_modules/`,
   `web/dist/`, `requirements-dev.txt`, and dev-only docs/config.
7. **Healthchecks and startup readiness (new — not in the original draft).** `depends_on`
   alone only waits for container *creation*, not application readiness, so:
   - Each of the three MCP servers gets a `/health` custom Starlette route (FastMCP's
     `@mcp.custom_route("/health", methods=["GET"])`) alongside the FastAPI backend's
     existing `/health`. TDD: `tests/mcp/test_health_endpoints.py`.
   - `docker-compose.yml` healthchecks (step 5) poll those endpoints; `backend`/`web` use
     `condition: service_healthy` in `depends_on` so they don't start against
     not-yet-ready dependencies.
   - The backend also **fails fast at startup** (FastAPI `lifespan`) with a clear
     `RuntimeError` if `BEDROCK_MODEL_ID` is unset, rather than only failing on the first
     `/chat` request. TDD: `tests/api/test_startup_validation.py`.
   - **Correction found during live verification, not anticipated by the original
     draft:** `mcp` (1.29.0)'s `FastMCP` auto-enables DNS-rebinding protection with
     `allowed_hosts` limited to `127.0.0.1`/`localhost`/`[::1]` variants, captured at
     construction time (default `host="127.0.0.1"`) — *before* each server's `__main__`
     block rebinds `host` to `0.0.0.0` for container use. Docker Compose peers reach each
     MCP server by its service name (e.g. `supermarket-mcp:8001`), and that Host header
     was rejected with `421 Misdirected Request`, discovered only when the real backend
     called a real MCP server over the compose network (`docker compose up` + a real
     `/chat` request) — the existing test suite never exercises the HTTP transport layer
     end-to-end, only `call_tool()` in-process. Fixed by passing an explicit
     `transport_security=TransportSecuritySettings(...)` to each `FastMCP(...)`
     constructor, adding that server's own compose hostname (`"supermarket-mcp:*"`,
     `"recipe-mcp:*"`, `"retailer-cart-mcp:*"`) alongside the existing localhost patterns.
     TDD: `tests/mcp/test_transport_security.py`.
8. **Ingestion fixtures (new — not in the original draft).** `python -m app.ingestion.run
   --source fixtures` reads `tests/fixtures/feeds/{shufersal,rami_levy}_sample.xml` — the
   shared `Dockerfile` copies only that subdirectory (step 1), not the whole `tests/`
   tree. Verified with `docker compose --profile tools run --rm ingestion` followed by a
   direct SQLite read from the `backend_data` volume (`docker run --rm -v
   ai-supermarket-agent_backend_data:/data python:3.11-slim python -c "..."`), confirming 5
   Shufersal + 5 Rami Levy rows actually landed in `/data/app.db` — not just that the
   process exited 0.
9. **AWS credentials and Bedrock.** `backend` mounts `${HOME}/.aws:/root/.aws:ro` — **local
   development only**, documented in `docker-compose.yml` and `.env.example`; Kubernetes
   (CP10/11) uses its own IAM-role/Secret-based mechanism instead, never a host bind-mount.
   `app/api/main.py`'s `lifespan` validates `BEDROCK_MODEL_ID` is set before the backend
   accepts traffic (step 7).
10. **Spoonacular configuration.** `SPOONACULAR_API_KEY: ${SPOONACULAR_API_KEY}` passed to
    `recipe-mcp` only. Live-verified: with a placeholder key, Spoonacular returns 401, and
    that failure is visible in `docker compose logs recipe-mcp` specifically (not lumped
    into a generic backend trace) — container-per-service isolation makes the failure
    attributable to Recipe MCP configuration by construction.
11. Write `.env.example` and `.env` (gitignored) with `DATABASE_URL`, `BEDROCK_MODEL_ID`,
    `AWS_REGION`, `SPOONACULAR_API_KEY`.
12. Write `scripts/smoke_test.sh`: builds, starts the stack, waits (with timeouts, not a
    fixed `sleep`) for backend `/health` and web root, checks `docker compose ps`, dumps
    logs for any non-running/unhealthy service on failure, and always tears down via a
    `trap ... EXIT`. Does **not** require a real Bedrock/Spoonacular call — only that every
    service starts and responds.
13. Run `docker compose build`, `docker compose --profile tools run --rm ingestion`,
    `docker compose up -d`, `./scripts/smoke_test.sh`; fix issues as found (this is where
    steps 3/7's corrections were discovered).
14. Manually verify (see **Testing Tasks** and **Live retailer verification** below), then
    commit.

## Testing Tasks

- [x] `scripts/smoke_test.sh` passes (backend `/health` and web root both reachable,
      correct exit code, always tears down).
- [x] `docker compose --profile tools run --rm ingestion` completes successfully **and**
      the shared SQLite volume actually contains the ingested rows (checked directly, not
      inferred from exit code).
- [x] Manual walkthrough of grocery-list flow via the real containerized backend + real
      Bedrock + real supermarket-mcp + real (fixture-ingested) database, both via `curl`
      and via a real browser (Playwright-driven screenshot of the rendered React UI
      through nginx, hitting the real `/api/chat` proxy).
- [x] Recipe flow: real recipe-mcp reached; with a placeholder `SPOONACULAR_API_KEY`, the
      401 is visible specifically in `recipe-mcp`'s own logs.
- [x] Retailer-choice / decline: choosing a retailer routes to `retailer-cart-mcp`;
      declining does not call it at all, even while it's stopped.
- [x] Missing-session `login_required`: verified against **both** real retailer adapters
      by temporarily moving the real captured session files aside, confirming
      `blocked_reason: "login_required"` with no browser launched, then restoring the
      files (verified byte-identical afterward).
- [x] Failure isolation: stopping `supermarket-mcp` fails grocery requests clearly (500,
      no hang); stopping `recipe-mcp` fails only recipe requests, not grocery requests;
      stopping `retailer-cart-mcp` fails only retailer-choice requests, not the grocery
      flow up to that point.
- [x] `pytest` (131 passed), `ruff check` (clean), `pytest --cov` (81%, no regression),
      `cd web && npm run build` all pass on the final code.

## Live retailer verification (Shufersal / Rami Levy)

Both real captured sessions (`sessions/shufersal.json`, `sessions/rami_levy.json`, from a
prior manual `login.py` run) were exercised directly against `retailer-cart-mcp`'s real
`prepare_retailer_cart` tool over the compose network — **reported separately, per
retailer, as required**; do not read this as "full live support" for either:

**Shufersal** — session loads (no `login_required`, no CAPTCHA block detected), real site
navigation succeeds, correct `cart_url`
(`https://www.shufersal.co.il/online/he/cart`) returned. Item search for a common Hebrew
grocery term ("חלב"/milk) returned `not_found` — the adapter's CSS selectors
(`[data-testid='product-tile']`) and search URL, documented in CP8 as "unverified
guesses... verify selectors manually against the live site periodically," do not match the
real site's current markup. Add-to-cart, quantity confirmation, and cart persistence were
**not exercised** because no item matched. **Status: wiring/session/blocking verified live;
selectors are stale — needs a follow-up selector-refresh pass (CP8 adapter maintenance, out
of CP9's scope).**

**Rami Levy** — same result: session loads, real site navigation succeeds, correct
`cart_url` (`https://www.rami-levy.co.il/cart`) returned, no block detected, item search
for the same term returned `not_found` (adapter's `.product-box` selectors / `/api/search`
URL are similarly unverified-guess-stale). **Status: wiring/session/blocking verified
live; selectors are stale — same follow-up needed.**

Neither adapter reached checkout, login, or payment at any point, by construction (no such
method exists in either adapter). No CAPTCHA/bot-block was encountered in either case, so
`detect_block()`'s CAPTCHA path was not exercised live.

## Acceptance Criteria

- Normal `docker compose up` runtime uses the **real** Shufersal and Rami Levy adapters
  (not the mock retailer site — that's test-only, exercised by `pytest`/CI against
  `tests/mcp/mock_site_server.py`).
- With a valid captured session, choosing a retailer attempts to prepare its **real** cart
  via Playwright against the real site.
- Without a valid session, the UI shows a graceful `login_required` result — no crash, no
  automatic login attempt.
- The system stops before checkout/payment/order submission, always.
- A developer with only Docker installed (no local Python/Node toolchain) can run
  `docker compose up` and use the full chat UI locally. "Only Docker installed" means no
  local Python/Node toolchain is required to *run* the stack — it does **not** mean no
  external configuration is needed: a valid `BEDROCK_MODEL_ID` (+ AWS credentials via the
  local-only `~/.aws` mount) is required for the agent to respond at all, a valid
  `SPOONACULAR_API_KEY` is required for the recipe flow, and a previously-captured session
  file is required for a real (non-`login_required`) retailer-cart attempt.
- Local Docker replaces the previous multi-terminal Python/Node workflow for running the
  stack.

## Risks

- Four backend-side containers (vs. one bundled image) is more moving parts locally —
  acceptable trade-off for matching how this will actually run in Kubernetes (CP11), where
  each MCP server is its own Deployment/Service anyway.
- `Dockerfile.retailer-cart-mcp`'s `playwright install --with-deps chromium` meaningfully
  increases that one image's size — acceptable since it's isolated from the other three
  images now.
- `./sessions/` is a local host directory mounted read-only into `retailer-cart-mcp` — it
  must exist (even empty) before `docker compose up`, and must never be committed (CP8's
  `.gitignore` entry covers this, verified still in effect).
- Both real retailer adapters' selectors are confirmed stale against the live sites as of
  this checkpoint (see **Live retailer verification**) — real add-to-cart is not currently
  functional end-to-end against either site, only the session/navigation/blocking-detection
  layer. This is a real, load-bearing limitation, not a hypothetical one.
- Running the shared image and the retailer-cart image as root (not a hardened non-root
  user) trades container-hardening for reliability of two host bind-mounts
  (`~/.aws`, `./sessions`) whose permissions/ownership don't reliably survive a non-root
  container uid under Docker Desktop. Kubernetes (CP10/11) removes the reason for this
  trade-off entirely (no host bind-mounts there).

## Notes

CP10/11 build `k8s/dev` Deployments from these same two Dockerfiles (one per MCP server
plus the backend, all from `Dockerfile`; `retailer-cart-mcp` from its own) — keep both
images self-contained (no host-path dependencies beyond environment variables and the
optional local AWS credentials mount). Kubernetes will need its own equivalent of the
`/data` SQLite volume (likely a PVC) and its own session-secret delivery mechanism (a
Kubernetes Secret, not `./sessions:...:ro`) — and, given this checkpoint's stale-selector
finding, a CP8-adapter-maintenance pass should happen before or alongside CP11's live
Kubernetes deployment, not be assumed already solved.

`app/agent/nodes/parse_request.py`'s `ParsedRequestSchema` gained a `field_validator`
(`mode="before"`) coercing `[]` to `None` for `recipe_query`/`retailer_preference`/
`brand_preference` — a minimal, behavior-preserving compatibility fix, not a CP9 deliverable
in itself. It was required because the real configured Bedrock model
(`openai.gpt-oss-20b-1:0`) returns `[]` instead of omitting/nulling an unset optional string
field in its tool-call output, which made every real grocery-list request fail Pydantic
validation — undiscoverable without running the real containerized stack against the real
model, which is exactly what CP9's live verification is for. It changes no parsing decision
for any field the model actually fills in (see `tests/agent/test_parsed_request_schema.py`).

## Definition of Done

- [x] `Dockerfile`, `Dockerfile.retailer-cart-mcp`, `web/Dockerfile`, `web/nginx.conf`,
      `docker-compose.yml`, `scripts/smoke_test.sh`, `.dockerignore`, `.env.example`
      created; `.env` created locally (gitignored).
- [x] `docker compose config` validates; `docker compose build` succeeds for all five
      images.
- [x] `docker compose --profile tools run --rm ingestion` populates the shared `/data`
      volume, verified directly.
- [x] `./scripts/smoke_test.sh` passes (exit 0), always tears down.
- [x] Manual walkthrough (grocery-list, recipe, retailer-choice, decline,
      missing-session `login_required`) confirmed against the real containerized stack,
      including one real-browser pass.
- [x] Live verification against real Shufersal and Rami Levy reported separately, with the
      stale-selector limitation documented rather than glossed over.
- [x] `pytest`, `ruff check`, `pytest --cov`, and `cd web && npm run build` all pass on the
      final code.
- [x] Committed with a message referencing CP9.
