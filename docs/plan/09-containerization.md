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
     health-check log and a working `curl localhost:3000` from the host). Using
     `127.0.0.1` explicitly in every service's healthcheck avoids relying on
     hosts-resolution order/address-family preference at all.
   - **`RETAILER_SESSIONS_DIR=/app/sessions`** with `./sessions:/app/sessions:ro` — real
     captured session files, read-only, never copied into any image.
   - **`${HOME}/.aws:/root/.aws:ro`** on `backend` only, documented as local-development-only
     (see step 10).
   - Ports: web `3000:80` (matches `web/vite.config.ts`'s local dev-server port, not
     Vite's own 5173 default, so the frontend is reachable at the same host port whether
     run via `docker compose up` or `npm run dev`), backend `8000:8000`, supermarket-mcp
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
       ports: ["3000:80"]
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
`prepare_retailer_cart` tool, both directly via `automation.py` and over the compose
network through the real container — **reported separately, per retailer, as required**.

**First pass** (selectors as originally written in CP8) found both adapters' CSS
selectors and Rami Levy's search URL were stale/wrong against the real sites — see
"selector refresh" below, since fixed.

**Selector refresh (CP9 follow-up, same session):** inspected both real sites' actual
markup live (Playwright, headless, using the captured sessions) and rewrote both
adapters' `search_and_match`/`add_to_cart`/`detect_block` against verified real
selectors. Also fixed a real, general bug found along the way: neither adapter
URL-encoded `item_name`/`item_code` before interpolating them into the search URL, so any
item name containing a reserved URL character (e.g. `%`, common in "X% milk"-style
product names) silently broke the search — fixed with `urllib.parse.quote()` in both.

**Shufersal — status: two real, deterministic bugs found and fixed (with tests); a third,
non-deterministic real-site flakiness issue remains open — not claimed as fully
reliable.** Session loads, real site navigation succeeds, search finds an exact match by
product name (`li.tileBlock[data-product-name=...]`).

**Bug 1 — tautological confirmation, found and fixed:** the first version of
`add_to_cart`'s confirmation step filled the quantity `<input>` and then read that *same*
input back — tautological, since it can only ever report the value this method itself
just wrote, regardless of whether the site's backend actually persisted the add. This
produced a real false positive live: the app reported an item `"added"` when the real
cart, checked independently, was still empty. Fixed to reload the page fresh and
re-query by the matched item_code before reading the quantity back — a genuine server
round-trip instead of a self-check. Re-verified after the fix, twice, each time
cross-checked against an independently fresh-reloaded page reading the real, server-side
cart badge/total directly (not the adapter's own report): cart count/total both increased
by the added item's real price both times.

**Bug 2 — same-context double-navigation permanently hides the add button, found and
fixed:** reported live by a user testing the running app (item "גלידה" → matched via
`name_fallback`) as a 30s `Locator.click` timeout waiting for `button.js-add-to-cart` to
become visible. Root-caused through 10+ isolated live reproductions (not guessed):
`search_and_match`'s original design searched by item_code first, then by name — two full
navigations in the same browser context — and *any* second navigation within one context
(regardless of what the first one was: the homepage visit, a code search, anything)
permanently hides that context's add-to-cart button, confirmed stuck even after 20+
seconds of active polling, not a brief widget-init delay a longer wait would fix. A
single-navigation, fresh context reproduced success every time. Fixed two ways together:
`automation.py`'s `prepare_cart_for_retailer` now gives each item its own fresh browser
context (reloading the same `storage_state`) instead of reusing one context/page for the
whole run; this adapter's `search_and_match` now searches by name only (the item_code
pre-search was always a wasted navigation anyway — fixture-style codes never match the
real site's own `P_xxxxx` internal codes). Both changes are covered by
`tests/mcp/test_retailer_cart_automation.py` (orchestration-level fake-adapter tests
asserting exact `detect_block` call counts/cleanup, plus the full mock-site integration
suite) — 140/140 tests pass after the change, confirming no regression to the tested
contract.

**Bug 2 fix confirmed against the exact reported case**, then a **third, unresolved
issue** surfaced one step later: re-running the exact same "גלידה" request afterward got
past the `js-add-to-cart` click (previously always stuck) but then got stuck on the
*next* click, `button.js-update-cart` — and, more tellingly, a *different* item
("חלב בקרטון 3% שומן") that had **fully succeeded moments earlier** with byte-for-byte
identical code failed the same way on a later run. That inconsistency — identical code,
identical item, different outcome — points to genuine timing/session variance on
Shufersal's side (most plausibly its personalization/analytics scripts, network
conditions, or A/B experiment assignment), not a deterministic client-side bug, and was
not chased further (diminishing returns on guessing at a third-party site's internal
timing without instrumenting Shufersal's own network requests, which wasn't undertaken
this session). Both clicks in `add_to_cart` now use a shortened 10s timeout (down from
Playwright's 30s default) so a stuck click fails fast rather than tying up the whole
request — this does not fix the flakiness, it only fails cheaper when it happens.

**Net effect:** add-to-cart is real, live-verified, and meaningfully more reliable than
before this pass (two confirmed root causes eliminated) — but it is explicitly **not**
100% reliable end-to-end, and that shouldn't be read into "selectors verified" language
elsewhere in this doc. `cart_url` (`https://www.shufersal.co.il/online/he/cart`) was
believed correct at this point in the session — **later found wrong, see the CP9
follow-up (2026-08-06) `get_cart_url` section below.** Never reached login, checkout, or
payment in any run, successful or not. Two further real limitations found and handled,
not glossed over:
- A one-time "how would you like to receive your order?" modal (`#assortmentModal`)
  blocks add-to-cart on an account with no delivery method/address configured yet — hit
  once during testing, confirmed via screenshot, now detected as `blocked_reason:
  "delivery_address_required"` rather than silently failing or hanging. Configuring a
  delivery address is account setup, not a per-request cart action, so — like login —
  it's intentionally left to the account owner, never automated.
- **A real, unintended side effect during this session's own testing, not caused by a
  normal user request:** a deliberately nonsense test query
  (`"zzz_no_such_product_zzz"`, used to probe the `not_found` path) tripped the
  pre-existing `name_fallback` behavior (unchanged by CP9 — documented CP8 design: fall
  back to the first search result when nothing truly matches, rather than reporting
  nothing found) and added an unintended, unidentified real item to the live cart. No
  checkout/payment was reached, but this is a genuine product-behavior question flagged
  for a separate decision, not resolved here: `name_fallback`'s "guess the first result"
  behavior can add something the user never asked for. Left unchanged pending explicit
  direction (see Risks).

**Shufersal — CP9 follow-up (2026-08-06): refactored from DOM clicks to the site's own
internal fetch/`window.ajaxCall` flow.** The DOM-click path above (bugs 1 and 2, both fixed)
still left one real, unresolved flakiness source: an intermittent stuck click on
`button.js-update-cart`, live-reproduced but never root-caused, that could make a request
fail non-deterministically even on an item that had just succeeded moments earlier with
identical code. Rather than keep chasing that blind, the adapter was rewritten to stop
clicking DOM elements at all and instead drive the site through its own internal, already-
authenticated JS/fetch flow — the same mechanism the site's own front-end uses, called from
inside `page.evaluate()`.

Before touching any code, the live site was independently re-verified end-to-end against a
real account with a real captured session, per an explicit checklist:
- `window.ajaxCall(url, jsonBody, callback, contentType, cartContext)` exists on the live
  page and its full source was read (not assumed from an unrelated reference project).
- The real search endpoint and response schema were captured directly:
  `GET /online/he/search/results?q=...&limit=...` returns JSON with a `results` array,
  each item carrying `code`, `name`, `sellingMethod.code`, and — the key discovery —
  `cartStatus: {inCart, qty, ...}`, giving authoritative server-side cart state per product
  without any DOM read.
- The exact `/cart/add` payload shape was captured from the site's own JS
  (`productCodePost`, `productCode`, `sellingMethod`, `qty`, `frontQuantity`, `comment`,
  `affiliateCode`, plus a `cartContext`), and confirmed to work against a real product.
- The call runs inside the page's existing authenticated session/cookies by construction —
  it's the same page, no separate auth handling was added.
- **A real add was confirmed to persist server-side two independent ways:** a fresh
  follow-up `search/results` call showed the new `cartStatus.qty`, and — going further than
  the checklist strictly required, to be sure — a full `page.reload()` followed by another
  fresh search call showed the same persisted quantity.
- **A real, non-obvious finding that shaped the design:** `/cart/add`'s response body
  is *not* a trustworthy success signal. A request with a completely fake product code
  (`"P_NOT_A_REAL_CODE_999999"`) returned HTTP 200 with an all-but-identical generic
  mini-cart HTML fragment to a real, successful add — no `success: false`, no distinct
  error shape, confirmed both via `ajaxCall`'s own return value and by intercepting the raw
  `/cart/add` network response directly. This means "failures return structured errors"
  could **not** be satisfied by trusting `ajaxCall`'s response at all — so the adapter
  never does. Every `add_to_cart` call is followed by an independent, fresh
  `search/results` round trip that reads back `cartStatus.qty` for the specific product
  code just added; only that counts as confirmation, and a mismatch (including the product
  not showing up at all) raises `QuantityNotConfirmedError` exactly like a site-side stock
  cap would.
- No checkout, payment, login automation, CAPTCHA bypass, or anti-bot evasion was added —
  none of this touches any of that surface by construction.

With verification confirmed, `mcp_servers/retailer_cart_mcp/adapters/shufersal.py` was
rewritten: `search_and_match` now does one navigation to establish the session, then reads
results from the `search/results` fetch (matching by exact case-insensitive name, falling
back to the first result, same policy as before — unchanged); `add_to_cart` calls
`window.ajaxCall('/cart/add', ...)` and confirms via the fresh-search round trip described
above, with **no DOM locator, no click, and no `page.reload()`** anywhere in the add path.
A new `UnsupportedSiteFlowError` (in `automation.py`, adapter-agnostic) is raised if
`window.ajaxCall` isn't a function on the loaded page or if the search/add calls themselves
fail unexpectedly — `detect_block()` also checks for `window.ajaxCall`'s existence up front
so a missing internal interface is reported as `unsupported_site_flow` and stops the whole
run cleanly, rather than being discovered piecemeal per item. There is deliberately no
fallback to the old DOM-click path if the internal interface disappears; that interface is
undocumented and can change without notice, and silently falling back to a known-flaky
alternative would be worse than a clear, structured failure.

Covered by 12 new unit tests (`tests/mcp/test_shufersal_adapter.py`) against a fake `page`
that scripts `evaluate()` responses — no real browser, no real site — pinning down
search-result matching, the fresh-search confirmation path, the quantity-mismatch failure,
and both `UnsupportedSiteFlowError` paths (missing `ajaxCall`, and an `ajaxCall` call itself
throwing). Then, going beyond unit tests, the actual refactored adapter (not a throwaway
script) was driven once more through the real `prepare_cart_for_retailer` orchestration
against the real site with the real captured session, end-to-end: matched, added via
`ajaxCall`, and confirmed via the fresh-search round trip — `blocked: false`,
`quantity_confirmed: 2.0`, no DOM interaction anywhere in the path. Full suite: 152/152
passing (140 prior + 12 new), lint clean.

**What this does and doesn't resolve, honestly:** this removes the two known DOM-click
fragility sources (stuck `js-add-to-cart`/`js-update-cart` clicks) and the double-navigation
bug entirely, since there's no click or second navigation left to get stuck. It does *not*
guarantee `/cart/add` itself always succeeds server-side for every product/stock
combination — that's exactly why independent confirmation via `cartStatus` stays mandatory
rather than trusting the call. And like the DOM path before it, this remains built on an
undocumented internal interface that Shufersal can change at any time without notice; the
`unsupported_site_flow` fallback exists specifically so that eventuality is reported
clearly instead of failing silently or being worked around.

**Real-cart disclosure:** live verification for this refactor (both the pre-refactor
scripted checks and the post-refactor end-to-end confirmation) added a real item — "לחם
אחיד פרוס" (sliced bread), quantity 2 — to the real account's live Shufersal cart, plus one
other real product at quantity 1 during an early payload-shape check. No checkout or
payment was reached in any of this. Flagged here rather than silently left in the cart.

**Shufersal — second CP9 follow-up (2026-08-06, same day): `get_cart_url` was returning a
broken link — found live, fixed.** Triggered by a real user report: a request for "גלידה"
(ice cream) was reported as `added`, but checking the cart via the app's own "Open cart on
Shufersal" link showed nothing there. Investigated live rather than guessed:
- `GET /online/he/cart` (the URL `get_cart_url` had been returning, "confirmed correct" in
  the earlier pass above — that check evidently never actually navigated to it) redirects
  to a generic fallback page (`/online/he/A?null`) with no cart content at all, in a fresh
  browser context. So did the one other plausible candidate found on the page,
  `/online/he/cart/cartsummary` — same broken redirect.
- There is **no dedicated, directly-linkable cart page on this site at all.** The header's
  "הסל שלי" ("my cart") control is `href="javascript:void(0)"`, not a URL — clicking it
  triggers a client-side flyout (`#cartContainer`) populated via the page's own JS/AJAX, not
  a navigation. Confirmed the flyout itself is accurate: reading `#cartContainer` directly
  (no URL involved) showed a real, non-zero cart total matching what search's `cartStatus`
  had already reported — the underlying add-and-confirm logic checked out fine independent
  of this bug.
- Fixed `get_cart_url` to return the site's real homepage (`{BASE_URL}/online/he/`, which
  loads correctly and shows an accurate cart-count badge in the header) instead of the
  broken `/online/he/cart` path, with a comment explaining there is no better direct link
  available on this site.

**What this does and doesn't explain about the original report:** this fully explains why
clicking "Open cart on Shufersal" showed nothing — that link never worked. It does **not**
by itself rule out the separate, still-open `name_fallback` question flagged just above (a
generic query like "גלידה" has no exact product-name match on this site and could still
silently resolve to an unrelated item); which of the two actually applied to that specific
"גלידה" report was not conclusively isolated this session, and remains open pending the
user's direction on `name_fallback` policy.

**Shufersal — third CP9 follow-up (2026-08-06, same day): match by `item_code` first, and
an unresolved session-identity question raised directly by the user.** The user re-tested
after the `get_cart_url` fix and reported the item still wasn't visible — but this time
verified independently by logging into the real site with their own credentials in their
own browser and finding the cart empty, directly contradicting this adapter's own
"added"/confirmed report and an independent re-check (a fresh search re-query plus the
site's own cart-flyout total, read directly, both agreeing with each other and with the
correct real price). Two separate things came out of investigating this, live:

1. **A real, fixable gap: matching relied on name comparison when it should have used
   `item_code` first.** The exact item the user's report was about (`4823097809785`,
   "גלידה בטעם וניל1קג RUD" in our locally-ingested catalog) is a genuine retailer
   barcode that matches the real site's own product code one-for-one — confirmed live. But
   `search_and_match` only ever compared *names*, and our feed's raw `ItemName` (brand/size
   concatenated with no spaces) doesn't exactly match the site's own cleaner display name
   for the same product, so exact-name matching was failing for correctly-resolved items
   and silently falling through to `name_fallback` even when the item_code was already
   known and correct. Fixed: `search_and_match` now matches by `item_code` first (see
   `mcp_servers/retailer_cart_mcp/adapters/shufersal.py`), which is strictly more reliable
   than name comparison whenever the caller already has a resolved product code — which,
   per the user, is always true by the time an item reaches Retailer-Cart MCP. Covered by
   3 new unit tests (16/16 in `test_shufersal_adapter.py`, 156/156 full suite).

2. **A cross-session "empty cart" report, chased hard, that turned out to be a false
   alarm — root-caused, not left open.** The user confirmed the captured session used the
   *same* account they were checking manually, which ruled out an account-mismatch theory.
   Investigated in order, each one ruled out concretely rather than assumed: (a) a
   freshly-recaptured `login.py` session, used within minutes, still didn't appear on the
   user's side — ruled out staleness; (b) `acceleratorSecureGUID`/`miglog-cart` stayed
   identical across fresh contexts and an account-restricted URL didn't redirect to login —
   the session was genuinely authenticated, not anonymous/guest; (c) a byte-for-byte network
   comparison between a genuine Playwright `.click()` on the real "add to cart" button and
   this adapter's `ajaxCall` request showed them landing the same way — ruled out request
   shape as the variable, since even a literal real click didn't appear on the user's side
   either. **The actual cause:** the user was checking an already-open, already
   logged-in browser tab, which doesn't refetch true server-side account state from a page
   load or a link click — only a fresh login (log out, log back in) forces that refetch.
   The add was genuinely reaching the real, cross-device account cart the entire time;
   confirmed once the user did a fresh login and saw it. No further adapter change resulted
   from this beyond the `item_code` matching and `get_cart_url` fixes above — both good
   improvements independently, but neither was the actual cause of what looked like a
   failure. Documented here at length because the investigation genuinely (and reasonably,
   given the evidence at each step) pointed toward several wrong conclusions — an
   account-identity mismatch, then a fundamental session-replay limitation — before the
   real, much simpler cause was found. Worth remembering next time a "says added but I
   don't see it" report comes in: check for a stale already-open tab before assuming the
   automation is at fault.

**Rami Levy — status: real search/navigation confirmed; add-to-cart blocked by an
apparent account-state prerequisite, not fully confirmed end-to-end.** Session loads, real
site navigation succeeds, the real front-end search URL is `/he/online/search?q=...`
(distinct from `/api/search?q=...`, a raw JSON API the site's own front-end calls
internally that the original adapter was mistakenly hitting directly — there is no
`.product-box` HTML anywhere on the real site). Tile identification via
`.product-img[alt]` and the add-to-cart stepper (`button.btn-acc.plus`, quantity shown in
`.num-span`, whole-units only — this site has no direct-fill quantity input, only a
+/- stepper, so `UnsupportedQuantityError` is raised for fractional quantities) were
captured from one successfully-rendered results page. On later attempts in the same
session, search-result tiles loaded as empty placeholders (image container present, no
`alt` text, no add-to-cart controls at all) — most likely the same kind of one-time
delivery/branch setup prerequisite confirmed for Shufersal, though no equivalent visible
prompt was found to directly confirm that specific cause for this site.
`detect_block()` now reports this placeholder state as `blocked_reason:
"assortment_unavailable"` (verified live, both directly and through the container)
rather than guessing further or letting a hover/click on a nonexistent button hang.
**Full add-to-cart was not re-confirmed end-to-end for this retailer** — an honest open
item, not claimed as done.

Neither adapter reached checkout, login, or payment at any point, by construction (no such
method exists in either adapter). No CAPTCHA/bot-block was encountered for either site, so
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
- Real-site selectors/endpoints drift over time by nature (see **Live retailer
  verification** — both adapters' CP8-era selectors were already stale by CP9 and have
  been refreshed against the real sites as of this checkpoint); expect this to need
  periodic re-verification, not a one-time fix. Shufersal no longer uses DOM
  selectors/clicks at all as of the CP9 fetch/`ajaxCall` refactor (see **Live retailer
  verification**), which removed the two known DOM-click flakiness sources entirely, but
  it remains built on an undocumented internal interface that can change without notice —
  `unsupported_site_flow` is the designed-for fallback if it does. Rami Levy is unchanged
  (still DOM-click-based) and unconfirmed end-to-end — blocked by an apparent account-state
  prerequisite (`assortment_unavailable`) not yet fully root-caused.
- `automation.py`'s `prepare_cart_for_retailer` now opens a fresh browser context per
  item (reloading `storage_state` each time) instead of reusing one context for the whole
  run — found necessary for Shufersal (reusing one context across multiple navigations
  permanently hid its add-to-cart button). This is heavier (one browser context per item
  instead of one per run) and applies to every adapter, including Rami Levy and the mock
  adapter, not just Shufersal; the mock-site integration suite already covers it (140/140
  tests pass), but a cart with many items now opens/closes many contexts in sequence —
  acceptable for the tested/observed cart sizes, worth watching if that changes.
- The pre-existing (CP8, unchanged by CP9) `name_fallback` matching behavior — falling
  back to the first search result when nothing truly matches a requested item, rather
  than reporting `not_found` — can add an item the user never asked for when a query
  matches nothing meaningfully (observed live during CP9 verification testing). Flagged
  as a real product-behavior question, deliberately left unchanged pending a separate,
  explicit decision — not silently fixed or hidden.
- Both real retailer sites appear to require one-time account setup (a delivery
  method/address) before add-to-cart fully works — confirmed directly for Shufersal
  (`#assortmentModal`), inferred but not directly confirmed for Rami Levy. Like login,
  this is intentionally never automated — it's the account owner's one-time setup, not a
  per-request cart action.
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
- [x] Live verification against real Shufersal and Rami Levy reported separately, across
      three passes: initial selectors, a selector-refresh follow-up, and a Shufersal-only
      refactor from DOM clicks to the site's internal fetch/`ajaxCall` flow. Shufersal's
      real add-to-cart confirmed working end-to-end on the refactored adapter, including a
      live run of the actual (non-mock) code path; Rami Levy's search/navigation
      confirmed, add-to-cart blocked by an unresolved `assortment_unavailable` condition —
      documented as an honest open item, not claimed as done.
- [x] Shufersal add-to-cart confirmed to persist to the real, cross-device account cart —
      not merely a session-scoped/automation-only cart. Verified by the account owner
      directly: an item added by this adapter appeared in the real account cart after a
      fresh login. **Known UX caveat, not a bug:** an already-open, already-logged-in
      Shufersal browser tab shows stale cart state and does not refetch it from a page load
      or a link click — only a fresh login (sign out, sign back in) forces a refetch. The
      app's success UI (`RetailerCartResultView.tsx`) now says this explicitly next to the
      "Open cart" link so a user checking an already-open tab isn't misled into thinking
      the add failed.
- [x] `pytest`, `ruff check`, `pytest --cov`, and `cd web && npm run build` all pass on the
      final code.
- [x] Committed with a message referencing CP9.
