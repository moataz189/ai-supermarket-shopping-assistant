# CP9 — Containerization & Docker Compose

Spec milestone: M4 (starts). Depends on: CP5, CP7, CP8.

> **Revision note (1):** this plan was corrected after initial implementation and live
> verification against the real Docker Compose stack (real Bedrock, real Shufersal/Rami
> Levy adapters, real captured sessions). The original draft's acceptance criteria
> incorrectly implied normal `docker compose up` runs against the mock retailer site — see
> "Real runtime vs. test-only mock site" below. All corrections found necessary during
> implementation are documented inline and in **Notes**.
>
> **Revision note (2):** the initial implementation used one shared `Dockerfile` for
> backend/supermarket-mcp/recipe-mcp/ingestion (each overriding `command:` in
> `docker-compose.yml`). That was refactored to **one dedicated Dockerfile per service**,
> each living inside its own service directory and copying/installing only what that
> service needs — see "Per-service Dockerfile structure" below. This section and "Key
> Design Decision" reflect the current (per-service) architecture; steps below are updated
> accordingly.

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
Each of the five runtime services (backend, three MCP servers, ingestion) has its **own
dedicated Dockerfile**, living inside that service's own directory, copying and installing
only the code/dependencies that service directly imports — no shared base image, no
`command:` overrides for normal startup (each image's own `CMD` is already correct). Only
`retailer-cart-mcp` installs Playwright's browser binaries, since it alone needs them.

## Per-service Dockerfile structure

```
app/api/Dockerfile               → backend        (app/agent, app/api, app/dietary)
app/api/requirements.txt
mcp_servers/supermarket_mcp/Dockerfile             (mcp_servers/supermarket_mcp, app/db)
mcp_servers/supermarket_mcp/requirements.txt
mcp_servers/recipe_mcp/Dockerfile                  (mcp_servers/recipe_mcp only)
mcp_servers/recipe_mcp/requirements.txt
mcp_servers/retailer_cart_mcp/Dockerfile           (mcp_servers/retailer_cart_mcp + Playwright)
mcp_servers/retailer_cart_mcp/requirements.txt
app/ingestion/Dockerfile         → ingestion CLI   (app/ingestion, app/db, tests/fixtures/feeds)
app/ingestion/requirements.txt
web/Dockerfile                   → nginx-served SPA (unchanged: multi-stage Node build)
```

Each per-service `requirements.txt` is a curated **subset** of the root `requirements.txt`
(still the source of truth for pinned versions — `make install`/CI/pytest use it in full),
determined by grepping each service's actual imports rather than guessing:

| Service | Installs | Excludes |
|---|---|---|
| backend (`app/api`) | fastapi, uvicorn, pydantic, mcp, langgraph, langgraph-checkpoint-sqlite, langchain-aws | sqlalchemy, httpx, playwright |
| supermarket-mcp | sqlalchemy, pydantic, mcp | fastapi, uvicorn, httpx, langgraph*, langchain-aws, playwright |
| recipe-mcp | pydantic, mcp, httpx | fastapi, uvicorn, sqlalchemy, langgraph*, langchain-aws, playwright |
| retailer-cart-mcp | pydantic, mcp, playwright | fastapi, uvicorn, sqlalchemy, httpx, langgraph*, langchain-aws |
| ingestion | sqlalchemy | everything else — no pydantic/mcp usage anywhere in `app/ingestion` or `app/db` |

(`*` = langgraph/langgraph-checkpoint-sqlite/langchain-aws are backend-only; `uvicorn`,
`starlette`, and `httpx` are already transitive dependencies of `mcp==1.29.0` itself, so MCP
servers get a working ASGI server without an explicit `uvicorn` line.) No cross-imports
exist between the three `mcp_servers/*` packages, and the backend never imports `app.db` or
any `mcp_servers.*` code directly (it only talks to MCP servers over HTTP) — confirmed by
grep before writing each Dockerfile, not assumed.

Resulting image sizes (`docker images`, arm64, `--no-cache` build):

| Image | Size |
|---|---|
| web | 76.5 MB |
| ingestion | 265 MB |
| recipe-mcp | 284 MB |
| supermarket-mcp | 319 MB |
| backend | 527 MB |
| retailer-cart-mcp | 2.35 GB (Playwright's Chromium download dominates) |

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
app/api/Dockerfile
app/api/requirements.txt
mcp_servers/supermarket_mcp/Dockerfile
mcp_servers/supermarket_mcp/requirements.txt
mcp_servers/recipe_mcp/Dockerfile
mcp_servers/recipe_mcp/requirements.txt
mcp_servers/retailer_cart_mcp/Dockerfile
mcp_servers/retailer_cart_mcp/requirements.txt
app/ingestion/Dockerfile
app/ingestion/requirements.txt
web/Dockerfile
web/nginx.conf
docker-compose.yml
scripts/smoke_test.sh
.dockerignore
.env.example
.env (gitignored)
```

## Detailed Implementation Steps

1. Write `app/api/Dockerfile` (backend only). Only its own curated `requirements.txt` is
   installed — never `requirements-dev.txt` — so this image stays free of
   pytest/ruff/flask/pytest-playwright and of packages other services need:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app

   COPY app/api/requirements.txt ./requirements.txt
   RUN pip install --no-cache-dir -r requirements.txt

   COPY app/__init__.py ./app/__init__.py
   COPY app/agent ./app/agent
   COPY app/api ./app/api
   COPY app/dietary ./app/dietary

   ENV PYTHONUNBUFFERED=1
   EXPOSE 8000

   RUN mkdir -p /data

   CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
   No `mcp_servers` code (the backend only talks to MCP servers over HTTP), no `app.db`
   (the backend never touches SQLite directly), no `app.ingestion`. `DATABASE_URL` isn't
   even set for this service — `/data` exists only so `CHECKPOINTER_BACKEND=sqlite` has
   somewhere to write if ever enabled.
2. Write `mcp_servers/supermarket_mcp/Dockerfile`, `mcp_servers/recipe_mcp/Dockerfile`, and
   `mcp_servers/retailer_cart_mcp/Dockerfile` — each copies only its own
   `mcp_servers/<name>` directory (plus `app/db` for supermarket-mcp, which is the only one
   that touches SQLite) and installs only its own curated `requirements.txt` subset (see
   "Per-service Dockerfile structure" table above). `retailer_cart_mcp`'s is the only one
   that additionally runs `python -m playwright install --with-deps chromium`. Example
   (`mcp_servers/retailer_cart_mcp/Dockerfile`):
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app

   COPY mcp_servers/retailer_cart_mcp/requirements.txt ./requirements.txt
   RUN pip install --no-cache-dir -r requirements.txt
   RUN python -m playwright install --with-deps chromium

   COPY mcp_servers/retailer_cart_mcp ./mcp_servers/retailer_cart_mcp

   ENV PYTHONUNBUFFERED=1
   EXPOSE 8003

   CMD ["python", "-m", "mcp_servers.retailer_cart_mcp.server"]
   ```
   All three (and the backend, and ingestion) run as **root**, not a hardened non-root
   user: `retailer-cart-mcp` bind-mounts `./sessions/` read-only at restrictive `0600`
   permissions (CP8's `login.py`), and `backend` bind-mounts the developer's `${HOME}/.aws`
   read-only for local Bedrock calls — a non-root container uid is not guaranteed to match
   the host uid Docker Desktop presents for either bind mount, which would silently break
   credential/session loading. Root reads both regardless (Linux DAC override), and both
   mounts are read-only so root can't modify or exfiltrate them any more than a non-root
   user could. Revisited for Kubernetes (CP10/11), which uses IAM-role/Secret-based
   credential and session delivery instead of host bind-mounts, where non-root becomes
   safe.
3. Write `app/ingestion/Dockerfile` (ingestion CLI only) — copies `app/ingestion`, `app/db`,
   and `tests/fixtures/feeds` (see step 9), installs only `sqlalchemy` (nothing in
   `app/ingestion`/`app/db` imports pydantic, mcp, or anything else in the root
   `requirements.txt`). Its `CMD` bakes in `--source fixtures` directly — the
   `docker-compose.yml` `ingestion` service needs no `command:` override.
4. Write `web/Dockerfile` (multi-stage: build the static SPA, serve with nginx) — unchanged
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
5. Write `web/nginx.conf` (serve the SPA with an `index.html` fallback; proxy `/api/` to the
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
6. Write `docker-compose.yml` — five runtime services, each `build.dockerfile` pointing at
   its own per-service Dockerfile (step 1–4), the backend wired to the other three by URL,
   plus `web` and the `tools`-profile `ingestion` service. **No `command:` overrides
   anywhere** — each Dockerfile's own `CMD` is already the right command for that service.
   Key corrections from the original (shared-image) draft, found during live verification:
   - **`/data` volumes, not `/app`** — `backend`, `supermarket-mcp`, and `ingestion` mount
     `backend_data:/data` and set `DATABASE_URL: sqlite:////data/app.db`; `recipe-mcp` and
     `retailer-cart-mcp` don't touch the database at all, so they get no data volume.
   - **Health-aware `depends_on`** — `backend` waits on `supermarket-mcp`, `recipe-mcp`,
     and `retailer-cart-mcp` with `condition: service_healthy`; `web` waits on `backend`
     the same way. See step 8.
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
     (see step 10).
   - Ports match the original draft: web `5173:80`, backend `8000:8000`, supermarket-mcp
     `8001:8001`, recipe-mcp `8002:8002`, retailer-cart-mcp `8003:8003`.
   ```yaml
   services:
     supermarket-mcp:
       build: { context: ., dockerfile: mcp_servers/supermarket_mcp/Dockerfile }
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
       build: { context: ., dockerfile: mcp_servers/recipe_mcp/Dockerfile }
       environment:
         SPOONACULAR_API_KEY: ${SPOONACULAR_API_KEY}
         PORT: "8002"
       ports: ["8002:8002"]
       healthcheck: # same python-urllib pattern against :8002/health

     retailer-cart-mcp:
       build: { context: ., dockerfile: mcp_servers/retailer_cart_mcp/Dockerfile }
       environment:
         PORT: "8003"
         RETAILER_SESSIONS_DIR: /app/sessions
       volumes: [ "./sessions:/app/sessions:ro" ]
       ports: ["8003:8003"]
       healthcheck: # same python-urllib pattern against :8003/health

     backend:
       build: { context: ., dockerfile: app/api/Dockerfile }
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
         - ${HOME}/.aws:/root/.aws:ro   # local dev only — see step 10
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
       build: { context: ., dockerfile: app/ingestion/Dockerfile }
       environment:
         DATABASE_URL: sqlite:////data/app.db
       volumes: [ "backend_data:/data" ]
       profiles: ["tools"]

   volumes:
     backend_data:
   ```
7. Write `.dockerignore` (new — not in the original draft): excludes `.git/`,
   `.worktrees/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, coverage
   artifacts, `*.db`, `.env*` (except `.env.example`), `sessions/`, `web/node_modules/`,
   `web/dist/`, `requirements-dev.txt`, and dev-only docs/config.
8. **Healthchecks and startup readiness (new — not in the original draft).** `depends_on`
   alone only waits for container *creation*, not application readiness, so:
   - Each of the three MCP servers gets a `/health` custom Starlette route (FastMCP's
     `@mcp.custom_route("/health", methods=["GET"])`) alongside the FastAPI backend's
     existing `/health`. TDD: `tests/mcp/test_health_endpoints.py`.
   - `docker-compose.yml` healthchecks (step 6) poll those endpoints; `backend`/`web` use
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
9. **Ingestion fixtures (new — not in the original draft).** `python -m app.ingestion.run
   --source fixtures` reads `tests/fixtures/feeds/{shufersal,rami_levy}_sample.xml` — the
   `app/ingestion/Dockerfile` copies only that subdirectory (step 3), not the whole `tests/`
   tree. Verified with `docker compose --profile tools run --rm ingestion` followed by a
   direct SQLite read from the `backend_data` volume (`docker run --rm -v
   ai-supermarket-agent_backend_data:/data python:3.11-slim python -c "..."`), confirming 5
   Shufersal + 5 Rami Levy rows actually landed in `/data/app.db` — not just that the
   process exited 0.
10. **AWS credentials and Bedrock.** `backend` mounts `${HOME}/.aws:/root/.aws:ro` — **local
   development only**, documented in `docker-compose.yml` and `.env.example`; Kubernetes
   (CP10/11) uses its own IAM-role/Secret-based mechanism instead, never a host bind-mount.
   `app/api/main.py`'s `lifespan` validates `BEDROCK_MODEL_ID` is set before the backend
   accepts traffic (step 8).
11. **Spoonacular configuration.** `SPOONACULAR_API_KEY: ${SPOONACULAR_API_KEY}` passed to
    `recipe-mcp` only. Live-verified: with a placeholder key, Spoonacular returns 401, and
    that failure is visible in `docker compose logs recipe-mcp` specifically (not lumped
    into a generic backend trace) — container-per-service isolation makes the failure
    attributable to Recipe MCP configuration by construction.
12. Write `.env.example` and `.env` (gitignored) with `DATABASE_URL`, `BEDROCK_MODEL_ID`,
    `AWS_REGION`, `SPOONACULAR_API_KEY`.
13. Write `scripts/smoke_test.sh`: builds, starts the stack, waits (with timeouts, not a
    fixed `sleep`) for backend `/health` and web root, checks `docker compose ps`, dumps
    logs for any non-running/unhealthy service on failure, and always tears down via a
    `trap ... EXIT`. Does **not** require a real Bedrock/Spoonacular call — only that every
    service starts and responds.
14. Run `docker compose build`, `docker compose --profile tools run --rm ingestion`,
    `docker compose up -d`, `./scripts/smoke_test.sh`; fix issues as found (this is where
    steps 3/7's corrections were discovered).
15. Manually verify (see **Testing Tasks** and **Live retailer verification** below), then
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
- `mcp_servers/retailer_cart_mcp/Dockerfile`'s `playwright install --with-deps chromium`
  makes that one image ~2.35 GB, dwarfing the other four (76.5 MB–527 MB) — acceptable
  since it's fully isolated in its own image and Dockerfile now, and doesn't inflate any
  other service.
- `./sessions/` is a local host directory mounted read-only into `retailer-cart-mcp` — it
  must exist (even empty) before `docker compose up`, and must never be committed (CP8's
  `.gitignore` entry covers this, verified still in effect).
- Both real retailer adapters' selectors are confirmed stale against the live sites as of
  this checkpoint (see **Live retailer verification**) — real add-to-cart is not currently
  functional end-to-end against either site, only the session/navigation/blocking-detection
  layer. This is a real, load-bearing limitation, not a hypothetical one.
- All five images run as root (not a hardened non-root user) — trades container-hardening
  for reliability of two host bind-mounts (`~/.aws` on `backend`, `./sessions` on
  `retailer-cart-mcp`) whose permissions/ownership don't reliably survive a non-root
  container uid under Docker Desktop. Kubernetes (CP10/11) removes the reason for this
  trade-off entirely (no host bind-mounts there).
- Five per-service `requirements.txt` files (plus the root one, still used for local
  dev/CI) means a new dependency has to be added in two places if a service starts
  importing something new: the root `requirements.txt` (version pin) and that service's
  own subset file. Not automated — a real maintenance cost of this refactor, traded for
  meaningfully smaller/more isolated images.

## Notes

CP10/11 build `k8s/dev` Deployments from these same five Dockerfiles (one per MCP server,
one for the backend, one for ingestion, each already scoped to exactly the code/deps that
service needs) — keep all five images self-contained (no host-path dependencies beyond
environment variables and the optional local AWS credentials mount). Kubernetes will need
its own equivalent of the
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

- [x] `app/api/Dockerfile`, `mcp_servers/supermarket_mcp/Dockerfile`,
      `mcp_servers/recipe_mcp/Dockerfile`, `mcp_servers/retailer_cart_mcp/Dockerfile`,
      `app/ingestion/Dockerfile`, `web/Dockerfile`, `web/nginx.conf`, each service's own
      `requirements.txt`, `docker-compose.yml`, `scripts/smoke_test.sh`, `.dockerignore`,
      `.env.example` created; `.env` created locally (gitignored).
- [x] `docker compose config` validates; `docker compose build --no-cache` succeeds for all
      six images (five default-profile + `ingestion` under `--profile tools`).
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
