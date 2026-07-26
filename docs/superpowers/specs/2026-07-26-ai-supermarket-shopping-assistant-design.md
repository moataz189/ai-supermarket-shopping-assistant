# AI Supermarket Shopping Assistant — Design

Date: 2026-07-26
Status: Approved for planning

## 1. Problem & Scope

Build an agent that takes natural-language shopping requests (groceries, recipes, cleaning
products, personal care, etc.), searches products across two Israeli supermarket chains
(Shufersal and Rami Levy), compares price/size/availability against the user's stated
preferences, and prepares an optimized shopping cart. For recipe requests, the agent extracts
ingredients via a recipe API before searching for matching products.

**Hard constraint**: the system never places an order or makes a payment. It stops after
preparing the cart and returns product/cart-adjacent links where possible.

**Project context**: solo developer, several weeks to build. This is a course/capstone final
project with a fixed checklist of required technologies (see Requirements Traceability, §9).

## 2. Architecture

```
┌─────────────┐     REST/JSON      ┌──────────────────┐
│  React SPA  │ ─────────────────▶ │  FastAPI backend │
│  (chat UI)  │ ◀───────────────── │                  │
└─────────────┘                    └────────┬─────────┘
                                             │ invokes
                                             ▼
                                  ┌───────────────────────┐
                                  │   LangGraph Agent      │
                                  │ (Claude via Amazon     │
                                  │  Bedrock Converse API) │
                                  └──────┬─────────┬───────┘
                          MCP tool calls │         │ MCP tool calls
                                         ▼         ▼
                       ┌──────────────────┐   ┌───────────────────────┐
                       │  Recipe MCP       │   │  Supermarket-Data MCP  │
                       │  server           │   │  server                │
                       │  (wraps           │   │  (product search/      │
                       │   Spoonacular)    │   │   offer lookup only)   │
                       └───────────────────┘   └───────────┬────────────┘
                                                            │ queries (SQLAlchemy)
                                                            ▼
                                                ┌───────────────────────┐
                                                │ Product DB             │
                                                │ SQLite (dev) /          │
                                                │ Postgres (prod)         │
                                                └───────────────────────┘
                                                            ▲
                                                            │ atomic upsert
                                                ┌───────────────────────┐
                                                │ Ingestion job           │
                                                │ (K8s CronJob in prod;   │
                                                │  manual/sample run in   │
                                                │  dev) — downloads/parses│
                                                │  Shufersal & Rami Levy  │
                                                │  price-transparency     │
                                                │  feeds                  │
                                                └───────────────────────┘

LangGraph checkpoint/state → DynamoDB (deployed dev/prod) or in-memory/SQLite
(local dev & tests) — enables interrupt/resume for clarification questions.
```

**Division of responsibility**: the Supermarket-Data MCP server is a data-access tool only
(search, offer lookup, comparison of specific candidates). All "shopping intelligence" —
cart optimization, applying budget/dietary/brand/store preferences — lives in the LangGraph
agent layer, not in the MCP server.

**Data source**: Israeli supermarkets are legally required (Price Transparency Law) to
publish machine-readable price/product feeds. This project ingests those bulk XML/GZIP files
rather than scraping live sites or using an unofficial API. Consequence: "availability" means
*the product is listed in the retailer's published feed*, not a live/real-time stock
guarantee. There is no official add-to-cart API, so the system never attempts real
cart/checkout — only best-effort product or retailer-search links.

## 3. Components

- **LangGraph Agent** — graph nodes: `parse_request` → (recipe path: `search_recipes` →
  [interrupt if ambiguous] → `get_recipe_ingredients`) → `search_products` →
  [interrupt if ambiguous match] → `optimize_cart` → `finalize`. Runs on Claude via the
  Amazon Bedrock Converse API. State persisted via a checkpointer so paused
  (awaiting-clarification) threads resume correctly.

- **Recipe MCP server** (custom, domain-specific) — tools:
  - `search_recipes(query)` — candidate recipes from Spoonacular.
  - `get_recipe(recipe_id)` — full recipe detail.
  - `get_recipe_ingredients(recipe_id, servings?)` — structured ingredient list, scaled to
    servings where Spoonacular supports it.

- **Supermarket-Data MCP server** (custom, domain-specific) — tools:
  - `search_product(query, store?)` — lightweight candidate list (name, sku, basic price
    where cheaply available).
  - `get_product_offers(sku)` — full per-store offer detail: price, `listed_in_feed`,
    `last_updated_at`. Called only for shortlisted candidates from `search_product`, to
    minimize MCP round-trips.
  - `compare_product(candidates[])` — compare a specific set of candidates.

- **Ingestion job** — downloads, validates, and atomically loads Shufersal & Rami Levy
  price-transparency feeds. Runs as a Kubernetes CronJob in deployed environments; run
  manually against sample/snapshot data for local dev.

- **FastAPI backend** — REST endpoints (`POST /chat`, etc.) fronting the LangGraph agent.
  No authentication in the MVP.

- **React SPA** — chat-style UI: message input, agent responses, inline clarification
  prompts, final cart display (items, store, unit price, subtotal, total vs. budget,
  per-item product/search link), missing-items and warning/staleness banners.

- **Product DB** — SQLAlchemy ORM + repository pattern. Models, repositories, and business
  logic are identical across environments; only `DATABASE_URL` changes:
  - Dev: `sqlite:///./app.db`
  - Prod: `postgresql+psycopg://user:password@host:5432/supermarket`

- **LangGraph checkpointer** — DynamoDB in deployed dev/prod; in-memory or SQLite
  checkpointer for local development and automated tests. Swappable via config only.

## 4. Data Flow

**Recipe request** (e.g. "shakshuka for 4 people, budget 150 shekels, no dairy"):

1. React SPA sends `POST /chat`. FastAPI's **first** response for a new conversation
   includes a `thread_id`; the client sends that same `thread_id` on every follow-up
   (including clarification answers) so the LangGraph checkpointer resumes the correct
   paused thread instead of starting a new one.
2. `parse_request` (Claude) classifies the request as a recipe request and extracts
   `{recipe_query, servings, budget, dietary constraints, store/brand preferences}`.
   Preferences are always supplied inline in the request — there is no persisted user
   profile in the MVP.
3. `search_recipes("shakshuka")` — if there is one clear top match, continue automatically;
   if multiple plausible matches, **interrupt** and ask the user to pick, before calling
   `get_recipe_ingredients` at all.
4. `get_recipe_ingredients(id, servings=4)` returns the scaled ingredient list.
5. For each ingredient: `search_product(name)` → shortlist candidates → `get_product_offers`
   only for the shortlist, across both stores.
6. **Dietary constraints** are applied at two points: at recipe selection (avoid recipes
   fundamentally incompatible with the constraint) and at product matching (a conflicting
   ingredient — e.g. dairy in a "no dairy" request — first tries a substitution; only if no
   substitution exists is it flagged/asked-about, never silently dropped).
7. If a specific ingredient has multiple plausible product matches, the graph **interrupts**
   and asks the user to choose, using the checkpointed thread to resume correctly.
8. `optimize_cart` runs in `shopping_mode: single_store` (the only mode in the MVP): check
   whether either store alone can cover the full cart; if one or both can, pick the cheaper
   fully-covering store; if neither can, score each store by a coverage+cost combination and
   pick the best-scoring single store. `cheapest_split` (mixing stores per item) is a
   documented future enhancement, not built now.
9. `finalize` returns the cart (items, store, price, product/search link), totals vs. budget,
   and a missing-items list with reasons.
10. React SPA renders the cart, inline clarification prompts, and missing items/warnings
    clearly separated.

**Direct grocery-list request** ("milk, bread, 2kg rice, dish soap") skips the recipe branch
(steps 3–4) — `parse_request` extracts the item list directly and proceeds to step 5.

## 5. Error Handling

- **Partial-failure tolerance**: a single failed MCP call never fails the whole request —
  the graph continues with what it has and reports the gap. **HTTP 503** is reserved for
  cases where the request cannot meaningfully continue at all (e.g. the entire
  Supermarket-Data MCP is unreachable, or the underlying Bedrock/LLM call fails).
- **Typed error codes**: `recipe_api_unavailable`, `recipe_not_found`, `mcp_timeout`,
  `product_not_found`, `product_lookup_failed`, `dietary_conflict`, `ingestion_failed`,
  `budget_exceeded`, `invalid_request`.
- **Retry policy**: only transient failures are retried (timeouts, rate limits, network
  errors, temporary 5xx) with one backoff retry. Validation errors and not-found results are
  never retried.
- **Response status vs. warnings**: API responses carry a `status` of `success` or
  `partial_success`. Conditions like `budget_exceeded`, stale retailer data, or a failed
  lookup for one item produce `partial_success` with a `warnings` array — these remain
  **HTTP 200**, since a usable cart was still produced.
- **Over-budget reporting**: response includes `total`, `budget`, and `over_budget_by`; the
  agent may suggest cheaper substitutions but never auto-removes items.
- **Atomic ingestion**: each run downloads and validates the *complete* feed for a chain,
  loads it into staging/a transaction, and swaps it in as the active dataset only after full
  validation succeeds. A failed/partial run never corrupts the live Product DB.
- **Per-retailer freshness**: each store's data carries its own independent
  `last_updated_at` and `stale` flag — e.g. Shufersal can be fresh while Rami Levy is stale,
  and this is surfaced per-retailer (never collapsed into one global flag) in both the API
  and the UI.
- **Malformed/unintelligible request**: if `parse_request` extracts nothing actionable, the
  agent asks a clarifying question rather than guessing.

## 6. Testing Strategy

- **Unit tests**: recipe ingredient parsing/scaling, product matching/scoring, cart
  optimization (`single_store` selection, budget math, dietary-substitution logic), ingestion
  feed parsing (XML/GZIP → normalized records) — pure logic, fixture data, no network.
- **Integration tests**: FastAPI endpoints against a real test DB (SQLite) and the two MCP
  servers exercised against recorded fixture responses (not live Spoonacular / live feeds),
  so tests are deterministic and independent of external services or rate limits.
- **Agent/graph tests**: the LangGraph graph run end-to-end with mocked MCP tool responses
  for key scenarios — direct grocery list, recipe path, ambiguous-recipe interrupt/resume,
  ambiguous-product interrupt/resume, missing-item reporting, over-budget reporting,
  dietary-substitution — using the in-memory/SQLite checkpointer.
- **Ingestion tests**: atomic-swap behavior (a failed/partial download must not corrupt
  existing data) and staleness detection.
- **CI**: GitHub Actions runs lint + unit + integration tests on every PR.
- **Not in scope**: automated tests making live calls to Shufersal/Rami Levy feeds or
  Spoonacular (manual/exploratory checks only), and load/performance testing.

## 7. CI/CD & Deployment (GitOps)

**Repo structure**: single repo; application code plus top-level `k8s/dev/` and `k8s/prod/`
manifest directories.

**GitHub Actions (CI)**: on every PR — lint, unit/integration tests. On merge to `main` —
build Docker images for all services (FastAPI/agent, Recipe MCP, Supermarket-Data MCP,
ingestion job, React SPA), push to Docker Hub, then commit an image-tag bump into `k8s/dev/`.

**ArgoCD (CD)**, running in the kubeadm cluster:
- **Dev `Application`**: watches `k8s/dev/`. Automated sync enabled, self-heal enabled,
  prune enabled — a merge to `main` flows through to the dev namespace automatically.
- **Prod `Application`**: watches `k8s/prod/`. Automated sync **disabled**. Promotion is a
  PR that copies the validated image tag(s) into `k8s/prod/`; once reviewed and merged,
  a human triggers a **manual ArgoCD sync** — prod never changes from a bare merge to main.

**Infrastructure**: Terraform provisions the EC2 instance(s) for the kubeadm cluster.
Kubernetes itself is self-managed via `kubeadm` (not EKS, not k3s) — one cluster with `dev`
and `prod` namespaces (not separate clusters). ArgoCD is installed into this cluster as part
of initial bootstrap.

**Monitoring**: Prometheus + Grafana track request latency, MCP call success/failure rates,
ingestion success and per-retailer staleness, and error-code counts.

## 8. MVP & Milestones (vertical slices)

MVP has **no authentication** — preferences (budget, dietary, brand, store) are supplied
inline in each request. Auth/Cognito + persisted user profiles are an explicit future
enhancement, not built now.

- **M1 — Core agent, local only.** LangGraph agent (parse → search → `single_store` optimize
  → finalize, with ambiguity interrupt/resume on an in-memory/SQLite checkpointer),
  Supermarket-Data MCP server, FastAPI, minimal React chat UI. Runs via docker-compose;
  SQLite dev DB seeded from a small sample of transparency data via a manual ingestion
  script run. Direct grocery-list requests only, no recipes yet.
- **M2 — Recipe path.** Recipe MCP server (`search_recipes`/`get_recipe`/
  `get_recipe_ingredients` with serving scaling), recipe-selection interrupt, dietary
  substitution logic at both recipe and product-matching stages.
- **M3 — Containerize & deploy to dev.** Dockerfiles for all services; Terraform provisions
  EC2 + kubeadm cluster; ArgoCD installed; `k8s/dev/` manifests; real ingestion CronJob
  against live Shufersal/Rami Levy feeds with atomic staging-swap; switch to Postgres +
  DynamoDB checkpointer in this deployed environment via config only.
- **M4 — CI/CD, prod, monitoring.** GitHub Actions pipeline (lint/test/build/push/manifest
  update) wired to ArgoCD dev auto-sync; `k8s/prod/` + manual-sync promotion flow;
  Prometheus + Grafana dashboards/alerts.
- **M5 — Hardening & polish.** Full test suite per §6; UI polish (clarification prompts,
  missing-items/warnings/stale-data display, over-budget reporting); README/docs.
- **Future enhancements (explicitly out of MVP)**: Cognito auth + persisted user profiles,
  `cheapest_split` shopping mode, additional retailers.

## 9. Requirements Traceability

| Requirement | Where addressed |
|---|---|
| Natural-language shopping requests (groceries, recipes, cleaning, personal care, etc.) | §4 `parse_request`, both request paths |
| Search Shufersal & Rami Levy, compare price/size/availability/preferences | §3 Supermarket-Data MCP, §4 steps 5–8 |
| Recipe requests via recipe API through custom MCP tool | §3 Recipe MCP server (Spoonacular) |
| Never orders/pays; stops after cart; returns links where possible | §1, §3 product/search links, §2 no cart/checkout API |
| LangGraph or LangChain agent | §2–§3 LangGraph agent |
| At least one MCP server | §3 (two: Recipe MCP, Supermarket-Data MCP) |
| Custom domain-specific MCP server | §3 (both are custom & domain-specific) |
| FastAPI | §3 FastAPI backend |
| Web UI | §3 React SPA |
| Kubernetes on AWS EC2 | §7 kubeadm cluster on Terraform-provisioned EC2 |
| Terraform | §7 |
| Dev and prod namespaces | §7, §8 M3/M4 |
| CI/CD | §7 GitHub Actions + ArgoCD GitOps |
| Prometheus and Grafana | §7 Monitoring |
| Unit and integration tests | §6 |

## 10. Out of Scope (MVP)

- User authentication, accounts, persisted preference profiles (Cognito planned as future
  enhancement).
- `cheapest_split` multi-store cart optimization.
- Real-time inventory guarantees (feed-based availability only).
- Live checkout/cart creation on retailer sites.
- Load/performance testing.
- Additional retailers beyond Shufersal and Rami Levy.
