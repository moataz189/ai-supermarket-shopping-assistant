# AI Supermarket Shopping Assistant — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan checkpoint-by-checkpoint.
> Each checkpoint has its own detailed plan under `docs/plan/`; read that file before
> starting the checkpoint's work. Steps within each checkpoint file use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Build an agent that turns a natural-language shopping request (grocery list or
recipe) into an optimized single-retailer shopping cart across Shufersal and Rami Levy,
respecting budget/dietary/brand/retailer preferences — and, once the user explicitly
approves that proposed cart, prepares the corresponding **real cart on the retailer's own
website** via browser automation, stopping before checkout, login, or payment. Ship it on a
self-managed Kubernetes cluster on AWS EC2 with GitOps CI/CD and monitoring.

**Architecture:** A LangGraph agent (Claude via Amazon Bedrock) orchestrates three custom MCP
servers — a Recipe MCP (wraps Spoonacular), a Supermarket-Data MCP (searches/prices ingested
retailer data), and a Retailer-Cart MCP (Playwright browser automation, invoked only after
user approval) — plus a deterministic dietary rule engine, behind a FastAPI backend and a
React chat UI. Retailer price-transparency feeds are ingested into a SQLAlchemy-backed
product database (SQLite locally, PostgreSQL when deployed). The Retailer-Cart MCP server
never performs search/pricing/optimization itself — it only acts on the cart the agent has
already decided, and only interacts with the retailer site to search for and add items,
never to check out. The whole stack runs on a kubeadm Kubernetes cluster on
Terraform-provisioned EC2, with `dev`/`prod` namespaces deployed via ArgoCD GitOps and
observed with Prometheus/Grafana. Full detail: `docs/spec.md`.

**Tech Stack:** Python, LangGraph, Amazon Bedrock (Claude, Converse API), MCP (Model Context
Protocol) servers, Playwright (Python, async API), FastAPI, SQLAlchemy, SQLite/PostgreSQL,
DynamoDB (LangGraph checkpointer, deployed envs), React (chat SPA), Docker, Terraform,
kubeadm on AWS EC2, ArgoCD, GitHub Actions, Prometheus, Grafana, pytest, `pytest-playwright`.

## Global Constraints

These apply to every checkpoint below; each checkpoint's plan assumes them without repeating
them.

- The system never places an order, makes a payment, or logs into a retailer account, at any
  point, in any checkpoint.
- Browser automation (Retailer-Cart MCP) only ever runs **after** the user has explicitly
  approved the proposed cart — never automatically, never speculatively.
- The Retailer-Cart MCP server's interface exposes only search/add-to-cart/cart-url actions.
  Checkout, login, and payment interactions are not implemented anywhere in that component —
  this is a structural guarantee, not just a runtime check.
- A failure to match or add a single item during browser automation never aborts the whole
  automation run; remaining items are still attempted, and the failure is reported per item.
- A detected CAPTCHA, bot-block, or login wall stops browser automation gracefully with a
  clear reason — never as an unhandled exception.
- Preferences (budget, dietary, brand, retailer, and the standing product-selection
  preference — cheapest / brand / vegan only / gluten-free only / no preference) are always
  supplied inline in the request/conversation — no user accounts/auth/persisted profiles in
  the MVP.
- Product-selection/ambiguity resolution applies identically to every shopping-list item
  regardless of source — an explicitly-named grocery item and a recipe-extracted ingredient
  go through the exact same search → shortlist → resolve step. Never special-case one path
  to skip asking when the other would ask.
- Auto-select only when there is truly one reasonable candidate, or the user already
  specified the exact product, or a standing preference resolves it; otherwise show a small
  shortlist (typically 3–5) and ask. Never silently pick a brand, package size, fat
  percentage, flavor, or dietary version when the choice is ambiguous and material.
- Once a product is resolved, its `ItemCode` is the fixed identifier used to compare that
  item across both retailers' Online stores — Shufersal Online is `StoreId 413`, Rami Levy
  Online is `StoreId 39` — for the rest of that request. If unavailable at one retailer,
  mark it unavailable there; never silently substitute a different product.
- Cart optimization is `single_retailer` only — never split a cart across retailers.
- "Availability" means *listed in the retailer's Online-store ingested feed*, never
  live/real-time stock; the retailer website is touched only for cart preparation after
  approval, never for search/pricing decisions.
- Application code must be identical across environments; only configuration
  (`DATABASE_URL`, checkpointer backend) changes between local dev/tests and deployed
  dev/prod namespaces.
- Dietary-restriction enforcement is deterministic (rule engine), never left to the LLM's
  discretion.
- No automated test may make a live call to Spoonacular, the Shufersal/Rami Levy feeds, or
  the real retailer websites; use recorded fixtures and a controlled mock retailer site.
- Every task ends with a passing test suite and a commit — do not move to the next
  checkpoint with a red build.

## Checkpoints

Each checkpoint maps to one detailed plan file under `docs/plan/`. Checkpoints are ordered;
later ones depend on earlier ones being done and committed.

| # | Checkpoint | Detail file | Spec milestone |
|---|---|---|---|
| CP1 | Project scaffolding & local dev environment | `docs/plan/01-project-scaffolding.md` | M1 |
| CP2 | Data model, database layer & ingestion pipeline | `docs/plan/02-data-model-ingestion.md` | M1 |
| CP3 | Supermarket-Data MCP server | `docs/plan/03-supermarket-mcp-server.md` | M1 |
| CP4 | LangGraph agent — grocery-list core flow | `docs/plan/04-langgraph-agent-core.md` | M1 |
| CP5 | FastAPI backend & React chat UI | `docs/plan/05-fastapi-react-ui.md` | M1 |
| CP6 | Recipe MCP server | `docs/plan/06-recipe-mcp-server.md` | M2 |
| CP7 | Recipe flow integration & dietary rule engine | `docs/plan/07-recipe-flow-dietary-engine.md` | M2 |
| CP8 | Retailer-Cart MCP server (Playwright) & cart-approval gate | `docs/plan/08-playwright-cart-automation.md` | M3 |
| CP9 | Containerization & docker-compose | `docs/plan/09-containerization.md` | M4 |
| CP10 | Terraform + kubeadm cluster on EC2 | `docs/plan/10-terraform-kubeadm-cluster.md` | M4 |
| CP11 | ArgoCD GitOps bootstrap & dev deployment | `docs/plan/11-argocd-gitops-dev.md` | M4 |
| CP12 | GitHub Actions CI/CD pipeline | `docs/plan/12-github-actions-cicd.md` | M5 |
| CP13 | Production namespace & promotion flow | `docs/plan/13-prod-namespace-promotion.md` | M5 |
| CP14 | Prometheus & Grafana monitoring | `docs/plan/14-monitoring-prometheus-grafana.md` | M5 |
| CP15 | Test suite hardening & demo resilience | `docs/plan/15-test-hardening-resilience.md` | M6 |
| CP16 | UI polish, docs & final demo readiness | `docs/plan/16-ui-polish-docs-demo.md` | M6 |

## Deliverables

By the end of CP5 (M1): a runnable, tested, local-only system (docker-compose, from CP9
onward) that turns a direct grocery-list request into a single-retailer proposed cart, with
clarification on ambiguous product matches, over a minimal chat UI.

By the end of CP7 (M2): the same system additionally accepts recipe requests, extracts and
scales ingredients via the Recipe MCP server, and enforces dietary constraints with
substitution-or-clarification behavior.

By the end of CP8 (M3): once the user explicitly approves a proposed cart, the system opens
the chosen retailer's website via Playwright, searches for and adds matched items/quantities
to the real cart, stops before checkout/login/payment, handles partial per-item failures
gracefully, and reports blocked automation (CAPTCHA/bot-detection/login-wall) as a clean
partial result — verified against a controlled mock retailer site in automated tests.

By the end of CP11 (M4): the full stack (including the Retailer-Cart MCP server) runs in the
`dev` namespace of a kubeadm cluster on AWS EC2 (provisioned by Terraform), deployed via
ArgoCD, ingesting real Shufersal/Rami Levy feeds on a schedule, backed by PostgreSQL and a
DynamoDB checkpointer.

By the end of CP14 (M5): every merge to `main` is linted, tested (including mock-site
browser-automation tests), built, and automatically deployed to `dev`; `prod` exists as a
separate namespace reachable only through a reviewed, manually-synced promotion;
Prometheus/Grafana dashboards show live operational metrics, including retailer-cart
preparation success/failure/blocked rates.

By the end of CP16 (M6): the full test suite (unit, integration, contract, agent/graph,
ingestion, concurrency, Postgres-compatibility, mock-site browser automation) passes in CI,
the UI clearly surfaces clarifications/cart-approval/real-cart results/missing
items/warnings/staleness, and the project is demo-ready end-to-end — including a live
(manually verified) walkthrough of real-site cart preparation as best-effort.

## Files Created/Modified (module map)

```
app/
  agent/           # LangGraph graph, nodes, state, checkpointer config      (CP4, CP7, CP8)
  dietary/         # deterministic dietary rule engine                       (CP7)
  db/
    models.py      # SQLAlchemy models: CanonicalProduct, RetailerOffer, ... (CP2)
    repositories.py# repository layer used by MCP server + ingestion         (CP2)
    session.py     # DATABASE_URL-driven engine/session setup                (CP2)
  ingestion/       # feed download, parse, validate, atomic staging load     (CP2, CP15)
  api/             # FastAPI app, routes, request/response schemas           (CP5, CP8)
mcp_servers/
  recipe_mcp/      # Recipe MCP server (Spoonacular)                        (CP6)
  supermarket_mcp/ # Supermarket-Data MCP server                            (CP3)
  retailer_cart_mcp/ # Retailer-Cart MCP server (Playwright)                 (CP8)
web/               # React chat SPA                                        (CP5, CP8, CP16)
infra/
  terraform/       # EC2 + kubeadm cluster provisioning                     (CP10)
k8s/
  dev/             # ArgoCD-watched dev namespace manifests                 (CP11)
  prod/            # ArgoCD-watched prod namespace manifests                (CP13)
  argocd/          # ArgoCD install + Application manifests                 (CP11)
  monitoring/      # Prometheus + Grafana manifests/dashboards              (CP14)
.github/workflows/ # CI/CD pipeline definitions                            (CP12)
tests/             # unit, integration, contract, agent, ingestion,
                   # mock-site browser-automation tests                    (all checkpoints)
docker-compose.yml # local dev stack                                       (CP9)
```

## Task Checklists

- [ ] CP1 — Project scaffolding & local dev environment
- [ ] CP2 — Data model, database layer & ingestion pipeline
- [ ] CP3 — Supermarket-Data MCP server
- [ ] CP4 — LangGraph agent — grocery-list core flow
- [ ] CP5 — FastAPI backend & React chat UI
- [ ] CP6 — Recipe MCP server
- [ ] CP7 — Recipe flow integration & dietary rule engine
- [ ] CP8 — Retailer-Cart MCP server (Playwright) & cart-approval gate
- [ ] CP9 — Containerization & docker-compose
- [ ] CP10 — Terraform + kubeadm cluster on EC2
- [ ] CP11 — ArgoCD GitOps bootstrap & dev deployment
- [ ] CP12 — GitHub Actions CI/CD pipeline
- [ ] CP13 — Production namespace & promotion flow
- [ ] CP14 — Prometheus & Grafana monitoring
- [ ] CP15 — Test suite hardening & demo resilience
- [ ] CP16 — UI polish, docs & final demo readiness

(Each box maps to one detail file under `docs/plan/`, which carries its own internal task
checklist — mark this box done only once that file's Definition of Done is fully met.)

## Requirements Traceability

Mirrors `docs/spec.md` §9, mapped to the checkpoints that implement each requirement.

| Requirement (spec §9) | Checkpoint(s) |
|---|---|
| Natural-language shopping requests (groceries, recipes, cleaning, personal care, etc.) | CP4, CP7 |
| Search Shufersal & Rami Levy, compare price/size/availability/preferences | CP2, CP3, CP4 |
| Product selection/ambiguity resolution applies uniformly to explicit items and recipe-derived ingredients | CP4, CP7 |
| Cross-retailer comparison by the same `ItemCode` at each retailer's Online store (`StoreId` 413 / 39) | CP2, CP3, CP4 |
| Recipe requests via recipe API through custom MCP tool | CP6, CP7 |
| Prepares the retailer's online cart but never proceeds to checkout, payment, or order submission | CP8 |
| Real cart preparation only after explicit user approval | CP8 |
| LangGraph or LangChain agent | CP4 |
| At least one MCP server | CP3 |
| Custom domain-specific MCP server | CP3, CP6, CP8 |
| FastAPI | CP5 |
| Web UI | CP5, CP16 |
| Kubernetes on AWS EC2 | CP10 |
| Terraform | CP10 |
| Dev and prod namespaces | CP11, CP13 |
| CI/CD | CP12, CP11, CP13 |
| Prometheus and Grafana | CP14 |
| Unit and integration tests | every checkpoint; consolidated in CP15 |

## Final Milestone

**Definition of "project complete":** all 16 checkpoints are checked off; the full automated
test suite (unit, integration, MCP contract, agent/graph, ingestion, concurrent-thread-id,
PostgreSQL-compatibility, mock-site browser-automation) passes in CI on `main`; the `dev`
namespace auto-deploys from `main` and is currently healthy; the `prod` namespace has at
least one manually-promoted, working deployment; Prometheus/Grafana dashboards are live and
show real traffic from a demo run, including retailer-cart-preparation metrics; and a full
walkthrough of `docs/spec.md` §12 (Acceptance Criteria) passes manually against the deployed
`prod` namespace as the final demo script — including one live (best-effort, manually
observed) real-site cart preparation against an actual Shufersal or Rami Levy product.
