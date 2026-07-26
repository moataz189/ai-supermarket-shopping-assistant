# AI Supermarket Shopping Assistant — Design

Date: 2026-07-26
Status: Approved for planning

## 1. Problem & Scope

**Problem**: Shopping across Israeli supermarket chains requires users to manually search
for each product, compare package sizes and prices, verify whether all requested items are
listed, and repeat the process when shopping from a recipe. This is time-consuming and makes
it difficult to understand which single retailer offers the best complete cart.

**Proposed solution**: The system converts a natural-language request into a structured
shopping list, retrieves matching products and offers from normalized supermarket
price-transparency data, and produces the best single-retailer cart while respecting budget,
dietary, brand, and retailer preferences. The agent understands requests for groceries,
recipes, cleaning products, personal care, and other supermarket items across two Israeli
chains (Shufersal and Rami Levy). For recipe requests, the agent extracts ingredients via a
recipe API before searching for matching products.

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
                                                ┌────────────────────────┐
                                                │ Product DB              │
                                                │ SQLite — local dev/tests │
                                                │ PostgreSQL — deployed    │
                                                │   dev & prod namespaces  │
                                                └────────────────────────┘
                                                            ▲
                                              validated staging load,
                                              atomic dataset activation
                                                            │
                                                ┌────────────────────────┐
                                                │ Ingestion job            │
                                                │ (K8s CronJob in deployed  │
                                                │  dev/prod; manual run     │
                                                │  against local/sample     │
                                                │  data for local dev) —    │
                                                │  downloads/parses         │
                                                │  Shufersal & Rami Levy    │
                                                │  price-transparency feeds │
                                                └────────────────────────┘

LangGraph checkpoint/state → DynamoDB (deployed dev/prod namespaces) or
in-memory/SQLite (local development & automated tests) — enables
interrupt/resume for clarification questions.
```

**Division of responsibility**: the Supermarket-Data MCP server is a data-access tool only
(search, offer lookup, comparison of specific candidates). All "shopping intelligence" —
cart optimization, applying budget/dietary/brand/retailer preferences — lives in the
LangGraph agent layer, not in the MCP server.

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
  - `search_product(query, retailer?)` — lightweight candidate list (name, `product_id`,
    basic price where cheaply available).
  - `get_product_offers(product_id)` — full per-retailer offer detail (aggregated across
    that retailer's branches — see Data Model below): price, `listed_in_feed`,
    `last_updated_at`. Called only for shortlisted candidates from `search_product`, to
    minimize MCP round-trips.
  - `compare_product(candidates[])` — compare a specific set of candidates.

- **Dietary rule engine** — a deterministic, structured rule set (not LLM judgment) that
  tags products/ingredients with attributes (e.g. `contains_dairy`, `contains_gluten`,
  `vegan`) and hard-filters/flags matches against the request's stated dietary constraints.
  The LLM (via `parse_request`) only extracts the constraint text and proposes candidate
  substitution products for the graph to check against this engine — it cannot override or
  reinterpret an explicit restriction.

- **Ingestion job** — downloads, validates, and loads Shufersal & Rami Levy
  price-transparency feeds via a validated staging load with atomic dataset activation (see
  §5). Runs as a Kubernetes CronJob in deployed dev/prod namespaces; run manually against
  sample/snapshot data for local development.

- **FastAPI backend** — REST endpoints (`POST /chat`, etc.) fronting the LangGraph agent.
  No authentication in the MVP. Generates the `thread_id` (see §4 API Contract Example).

- **React SPA** — chat-style UI: message input, agent responses, inline clarification
  prompts, final cart display (items, retailer, unit price, subtotal, total vs. budget,
  per-item product/search link), missing-items and warning/staleness banners.

- **Product DB** — SQLAlchemy ORM + repository pattern. Models, repositories, and business
  logic are identical across environments; only `DATABASE_URL` changes:
  - Local development/tests: `sqlite:///./app.db`
  - Deployed dev & prod namespaces: `postgresql+psycopg://user:password@host:5432/supermarket`

- **LangGraph checkpointer** — DynamoDB in deployed dev/prod namespaces; in-memory or SQLite
  checkpointer for local development and automated tests. Swappable via config only.

### Data Model: Canonical Products & Retailer Offers

Prices are not shared across retailers by a common SKU. The data model separates:

- **CanonicalProduct** — `product_id` (internal), `barcode` (EAN/UPC, when known and
  reliable), `name`, `category`, `package_size` (numeric), `package_unit` (normalized:
  g / kg / ml / l / unit).
- **RetailerOffer** — `retailer` (`shufersal` | `rami_levy`), `branch_id` (the specific
  physical branch published in that retailer's price-transparency feed — retailers publish
  per-branch, and prices can differ by branch), `retailer_product_code` (the retailer's own
  item code from the feed), `barcode` (as published by that retailer, used to join to a
  `CanonicalProduct`), `price`, `listed_in_feed`, `last_updated_at`.

Canonical products are matched across retailers primarily by `barcode` when present and
consistent; when the barcode is missing or unreliable, matching falls back to fuzzy
name+package-size similarity (used by `search_product`'s candidate shortlist).

**Retailer vs. branch**: "store" in earlier drafts of this spec meant **retailer** (the
chain — Shufersal or Rami Levy), not a specific physical branch. Since feeds are published
per-branch, cart optimization's `single_store` mode is precisely scoped as
**`single_retailer`**: for MVP, `get_product_offers` aggregates to retailer level by taking
the **minimum price across that retailer's branches** (retaining the winning `branch_id` for
traceability/links). Letting the user pick or filter by a specific branch/location is a
future enhancement, not built now.

**Package/unit normalization**: every offer's price is normalized to a `unit_price`
(price ÷ normalized quantity, e.g. ₪/kg, ₪/liter, ₪/unit) so differently-sized packages of
the same product (or candidate substitute products) can be compared on a like-for-like
basis. Cart optimization and substitution scoring use this `unit_price`, never raw shelf
price.

## 4. Data Flow

**Recipe request** (e.g. "shakshuka for 4 people, budget 150 shekels, no dairy"):

1. React SPA sends `POST /chat`. For a new conversation, the **FastAPI backend generates**
   the `thread_id` and returns it in the first response; the client only **reuses** that
   same `thread_id` on every follow-up (including clarification answers) — it never
   generates its own — so the LangGraph checkpointer resumes the correct paused thread
   instead of starting a new one.
2. `parse_request` (Claude) classifies the request as a recipe request and extracts
   `{recipe_query, servings, budget, dietary constraints, retailer/brand preferences}`.
   Preferences are always supplied inline in the request — there is no persisted user
   profile in the MVP.
3. `search_recipes("shakshuka")` — if there is one clear top match, continue automatically;
   if multiple plausible matches, **interrupt** and ask the user to pick, before calling
   `get_recipe_ingredients` at all.
4. `get_recipe_ingredients(id, servings=4)` returns the scaled ingredient list.
5. For each ingredient: `search_product(name)` → shortlist candidates → `get_product_offers`
   only for the shortlist, across both retailers.
6. **Dietary constraints** are applied at two points via the deterministic dietary rule
   engine (not left to LLM discretion): at recipe selection (avoid recipes fundamentally
   incompatible with the constraint) and at product matching (a conflicting ingredient —
   e.g. dairy in a "no dairy" request — first tries a substitution; only if no substitution
   exists is it flagged/asked-about, never silently dropped). The LLM may propose candidate
   substitutions, but the rule engine has final say on whether a product violates a stated
   restriction.
7. If a specific ingredient has multiple plausible product matches, the graph **interrupts**
   and asks the user to choose, using the checkpointed thread to resume correctly.
8. `optimize_cart` runs in `shopping_mode: single_retailer` (the only mode in the MVP): check
   whether either retailer alone can cover the full cart; if one or both can, pick the
   cheaper fully-covering retailer; if neither can, score each retailer by a coverage+cost
   combination and pick the best-scoring single retailer. `cheapest_split` (mixing retailers
   per item) is a documented future enhancement, not built now.
9. `finalize` returns the cart (items, retailer, price, product/search link), totals vs.
   budget, and a missing-items list with reasons.
10. React SPA renders the cart, inline clarification prompts, and missing items/warnings
    clearly separated.

**Direct grocery-list request** ("milk, bread, 2kg rice, dish soap") skips the recipe branch
(steps 3–4) — `parse_request` extracts the item list directly and proceeds to step 5.

### API Contract Example — `POST /chat`

First request (new conversation):

```json
{ "message": "shakshuka for 4 people, budget 150 shekels, no dairy" }
```

Response — `needs_clarification` (ambiguous recipe match; backend-generated `thread_id`):

```json
{
  "thread_id": "b3f1c2e0-9e2a-4b7a-8b1a-3d2f6a9c0e11",
  "status": "needs_clarification",
  "clarification": {
    "reason": "ambiguous_recipe",
    "question": "I found a few shakshuka recipes — which one did you mean?",
    "options": [
      { "id": "rec_101", "label": "Classic Shakshuka" },
      { "id": "rec_204", "label": "Green Shakshuka (spinach)" }
    ]
  },
  "cart": null,
  "warnings": []
}
```

Follow-up request (client reuses the returned `thread_id`; it never generates its own):

```json
{ "thread_id": "b3f1c2e0-9e2a-4b7a-8b1a-3d2f6a9c0e11", "message": "the classic one" }
```

Final response:

```json
{
  "thread_id": "b3f1c2e0-9e2a-4b7a-8b1a-3d2f6a9c0e11",
  "status": "partial_success",
  "clarification": null,
  "cart": {
    "retailer": "shufersal",
    "items": [
      {
        "product_id": "p_5521",
        "name": "Eggs, 12ct",
        "unit_price": 1.5,
        "qty": 1,
        "subtotal": 18.0,
        "link": "https://www.shufersal.co.il/online/he/search?text=eggs"
      }
    ],
    "total": 142.0,
    "budget": 150.0,
    "over_budget_by": 0
  },
  "warnings": [
    { "code": "product_not_found", "message": "Couldn't find harissa paste at either retailer." }
  ]
}
```

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
- **Response status vs. warnings**: API responses carry a `status` of `success`,
  `partial_success`, or `needs_clarification` (set whenever the graph has interrupted and is
  waiting on a clarification answer — recipe ambiguity or product-match ambiguity).
  Conditions like `budget_exceeded`, stale retailer data, or a failed lookup for one item
  produce `partial_success` with a `warnings` array — these remain **HTTP 200**, since a
  usable cart was still produced.
- **Over-budget reporting**: response includes `total`, `budget`, and `over_budget_by`; the
  agent may suggest cheaper substitutions but never auto-removes items.
- **Atomic ingestion**: each run downloads and validates the *complete* feed for a chain,
  loads it into a staging table/transaction, and activates it as the active dataset only
  after full validation succeeds — a validated staging load followed by atomic dataset
  activation. A failed/partial run never corrupts the live Product DB.
- **Per-retailer freshness**: each retailer's data carries its own independent
  `last_updated_at` and `stale` flag — e.g. Shufersal can be fresh while Rami Levy is stale,
  and this is surfaced per-retailer (never collapsed into one global flag) in both the API
  and the UI.
- **Demo resilience fallback**: if a live retailer feed is temporarily unavailable (e.g. at
  demo time), the ingestion job can be pointed at a recent stored feed snapshot instead of
  the live URL — same fetch interface, same download→validate→stage→atomic-activate code
  path — so the demo isn't blocked by an external feed being unreachable.
- **Malformed/unintelligible request**: if `parse_request` extracts nothing actionable, the
  agent asks a clarifying question rather than guessing.

## 6. Testing Strategy

- **Unit tests**: recipe ingredient parsing/scaling, product matching/scoring, cart
  optimization (`single_retailer` selection, budget math, dietary-substitution logic),
  ingestion feed parsing (XML/GZIP → normalized records) — pure logic, fixture data, no
  network.
- **Integration tests**: FastAPI endpoints against a real test DB (SQLite) and the two MCP
  servers exercised against recorded fixture responses (not live Spoonacular / live feeds),
  so tests are deterministic and independent of external services or rate limits.
- **MCP contract tests**: each MCP tool's request/response is validated against its
  documented schema independently of the agent graph, catching drift between an MCP server's
  actual behavior and what the agent expects.
- **Agent/graph tests**: the LangGraph graph run end-to-end with mocked MCP tool responses
  for key scenarios — direct grocery list, recipe path, ambiguous-recipe interrupt/resume,
  ambiguous-product interrupt/resume, missing-item reporting, over-budget reporting,
  dietary-substitution — using the in-memory/SQLite checkpointer.
- **Concurrent thread_id isolation tests**: verify that two different `thread_id`s
  progressing concurrently never leak state into each other's checkpoint.
- **PostgreSQL/Alembic CI compatibility test**: a CI job runs Alembic migrations (and a
  representative query smoke test) against a real PostgreSQL service container — not just
  SQLite — catching SQLite-only-compatible migrations/queries that would break in deployed
  dev/prod.
- **Ingestion tests**: atomic-swap behavior (a failed/partial download must not corrupt
  existing data) and staleness detection.
- **CI**: GitHub Actions runs lint + unit + integration tests (including the Postgres/Alembic
  job) on every PR.
- **Not in scope**: automated tests making live calls to Shufersal/Rami Levy feeds or
  Spoonacular (manual/exploratory checks only), and load/performance testing.

## 7. CI/CD & Deployment (GitOps)

**Repo structure**: single repo; application code plus top-level `k8s/dev/` and `k8s/prod/`
manifest directories.

**GitHub Actions (CI)**: on every PR — lint, unit/integration tests. On merge to `main` —
build Docker images for all services (FastAPI/agent, Recipe MCP, Supermarket-Data MCP,
ingestion job, React SPA), tag each image with the **immutable Git commit SHA** (never
`latest` or another mutable tag), push to Docker Hub, then commit that exact SHA into
`k8s/dev/`'s manifests. This manifest-bump commit is pushed using the default `GITHUB_TOKEN`
(not a personal access token) — GitHub does not trigger new workflow runs for pushes made
with the default token, so this commit does not re-trigger CI and cause a loop.

**ArgoCD (CD)**, running in the kubeadm cluster:
- **Dev `Application`**: watches `k8s/dev/`. Automated sync enabled, self-heal enabled,
  prune enabled — a merge to `main` flows through to the dev namespace automatically.
- **Prod `Application`**: watches `k8s/prod/`. Automated sync **disabled**. Promotion is a
  PR that copies the exact, already-validated image SHA tag(s) from `k8s/dev/` into
  `k8s/prod/` (never a different or newer build) ; once reviewed and merged, a human
  triggers a **manual ArgoCD sync** — prod never changes from a bare merge to main.
- **Bootstrap (one-time)**: during initial cluster setup (M3), ArgoCD is installed into the
  cluster and the `dev` and `prod` `Application` manifests are applied once, directly
  (`kubectl apply`), not through the pipeline. After this one-time bootstrap, all further
  deployments are GitOps-only — no direct `kubectl apply` or Terraform steps for application
  changes, only Git commits to `k8s/dev/` or `k8s/prod/` that ArgoCD picks up.

**Infrastructure**: Terraform provisions the EC2 instance(s) for the kubeadm cluster.
Kubernetes itself is self-managed via `kubeadm` (not EKS, not k3s) — one cluster with `dev`
and `prod` namespaces (not separate clusters).

**Monitoring**: Prometheus + Grafana track request latency, MCP call success/failure rates,
ingestion success and per-retailer staleness, and error-code counts.

## 8. MVP & Milestones (vertical slices)

MVP has **no authentication** — preferences (budget, dietary, brand, retailer) are supplied
inline in each request. Auth/Cognito + persisted user profiles are an explicit future
enhancement, not built now.

- **M1 — Core agent, local only.** LangGraph agent (parse → search → `single_retailer`
  optimize → finalize, with ambiguity interrupt/resume on an in-memory/SQLite checkpointer),
  Supermarket-Data MCP server, FastAPI, minimal React chat UI. Runs via docker-compose;
  local SQLite DB seeded from a small sample of transparency data via a manual ingestion
  script run. Direct grocery-list requests only, no recipes yet.
- **M2 — Recipe path.** Recipe MCP server (`search_recipes`/`get_recipe`/
  `get_recipe_ingredients` with serving scaling), recipe-selection interrupt, dietary rule
  engine + substitution logic at both recipe and product-matching stages.
- **M3 — Containerize & deploy to dev.** Dockerfiles for all services; Terraform provisions
  EC2 + kubeadm cluster; one-time ArgoCD bootstrap; `k8s/dev/` manifests; real ingestion
  CronJob against live Shufersal/Rami Levy feeds with validated staging load + atomic
  activation; switch to PostgreSQL + DynamoDB checkpointer in this deployed environment via
  config only.
- **M4 — CI/CD, prod, monitoring.** GitHub Actions pipeline (lint/test/build/push/manifest
  update with immutable SHA tags) wired to ArgoCD dev auto-sync; `k8s/prod/` + manual-sync
  promotion flow; Prometheus + Grafana dashboards/alerts.
- **M5 — Hardening & polish.** Full test suite per §6; UI polish (clarification prompts,
  missing-items/warnings/stale-data display, over-budget reporting); README/docs.
- **Future enhancements (explicitly out of MVP)**: Cognito auth + persisted user profiles,
  `cheapest_split` multi-retailer cart optimization, branch-specific (vs. retailer-wide
  minimum-price) optimization, additional retailers.

## 9. Requirements Traceability

| Requirement | Where addressed |
|---|---|
| Natural-language shopping requests (groceries, recipes, cleaning, personal care, etc.) | §4 `parse_request`, both request paths |
| Search Shufersal & Rami Levy, compare price/size/availability/preferences | §3 Supermarket-Data MCP + Data Model, §4 steps 5–8 |
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
- `cheapest_split` multi-retailer cart optimization.
- Branch-specific cart optimization (MVP uses each retailer's minimum price across its
  branches).
- Real-time inventory guarantees (feed-based availability only).
- Live checkout/cart creation on retailer sites.
- Load/performance testing.
- Additional retailers beyond Shufersal and Rami Levy.
