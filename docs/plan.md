# AI Supermarket Shopping Assistant — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan checkpoint-by-checkpoint.
> Each checkpoint has its own detailed plan under `docs/plan/`; read that file before
> starting the checkpoint's work. Steps within each checkpoint file use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Build an agent that turns a natural-language shopping request (grocery list or
recipe) into two independently-optimized shopping carts — one per retailer (Shufersal
Online, Rami Levy Online) — respecting budget/dietary/brand preferences, and lets the user
choose which to proceed with. Once chosen, prepares the corresponding **real cart on that
retailer's own website** via browser automation, stopping before checkout, login, or
payment. Ship it on a self-managed Kubernetes cluster on AWS EC2 with GitOps CI/CD and
monitoring.

**Architecture:** A LangGraph agent (Claude via Amazon Bedrock) orchestrates three custom MCP
servers — a Recipe MCP (wraps Spoonacular), a Supermarket-Data MCP (searches/prices **one
retailer's own catalog per call** — never cross-retailer), and a Retailer-Cart MCP
(Playwright, invoked only for the retailer the user chose) — plus a deterministic dietary
rule engine, behind a FastAPI backend and a React chat UI. **All three MCP servers are
long-lived HTTP services** (MCP's streamable-HTTP transport), each its own process/container/
Kubernetes Deployment reachable by the backend over the network by URL — not subprocesses
spawned over stdio. Each retailer's price-transparency feed is ingested into its **own
independent catalog** in a SQLAlchemy-backed database (SQLite locally, PostgreSQL when
deployed) — there is no canonical cross-retailer product table. The Retailer-Cart MCP server
never searches/prices/optimizes; it only acts on the already-built cart for the one retailer
chosen. The whole stack runs on a kubeadm Kubernetes cluster on Terraform-provisioned EC2,
with `dev`/`prod` namespaces deployed via ArgoCD GitOps and observed with Prometheus/Grafana.
Full detail: `docs/spec.md`.

**Tech Stack:** Python, LangGraph, Amazon Bedrock (Claude, Converse API), MCP (Model Context
Protocol) servers, Playwright (Python, async API), FastAPI, SQLAlchemy, SQLite/PostgreSQL,
DynamoDB (LangGraph checkpointer, deployed envs), React (chat SPA), Docker, Terraform,
kubeadm on AWS EC2, ArgoCD, Helm (third-party add-ons only, e.g. `kube-prometheus-stack`),
GitHub Actions, Prometheus, Grafana, pytest, `pytest-playwright`.

## Global Constraints

These apply to every checkpoint below; each checkpoint's plan assumes them without repeating
them.

- The system never places an order, makes a payment, or logs into a retailer account, at any
  point, in any checkpoint.
- All three MCP servers run as **long-lived HTTP services**, each reachable at its own URL —
  never spawned as a stdio subprocess. Each has its own container/Deployment from CP9/CP11
  onward; local dev must have them already running before the backend starts.
- Browser automation (Retailer-Cart MCP) only ever runs for the retailer the user **chose**
  after seeing both proposed carts — never automatically, never for the retailer not chosen.
- The Retailer-Cart MCP server's interface exposes only search/add-to-cart/cart-url actions.
  Checkout, login, and payment are not implemented anywhere in that component — structural,
  not a runtime check.
- A failure to match/add one item during browser automation never aborts the run; the
  failure is reported per item.
- A detected CAPTCHA, bot-block, or login wall stops browser automation gracefully with a
  clear reason — never an unhandled exception.
- Preferences (budget, dietary, brand, retailer, and the standing product-selection
  preference — cheapest / brand / vegan only / gluten-free only / no preference) are always
  supplied inline in the conversation — no user accounts/auth/persisted profiles in the MVP.
- Item resolution/ambiguity handling applies identically regardless of source (typed vs.
  recipe-derived), **once per item, not once per retailer**: a merged shortlist across both
  retailers' catalogs, auto-selected when unambiguous, asked about otherwise.
- **No canonical cross-retailer product identity.** Each retailer's catalog is independent,
  keyed by `(retailer, item_code)` at a fixed `StoreId` (Shufersal `413`, Rami Levy `39`).
  The agent builds a complete cart **independently for each retailer**, then compares totals
  — it never tries to match "the same" product across retailers.
- Budget is a **soft, best-effort** constraint per retailer, never a hard failure. An
  over-budget cart is still shown with trade-off suggestions (cheaper brand, private-label,
  smaller package, last-resort item removal) — never auto-applied without explicit approval.
- "Availability" means *listed in that retailer's Online-store feed*, never live stock; the
  retailer website is touched only after the user's choice, never for search/pricing.
- Application code must be identical across environments; only configuration
  (`DATABASE_URL`, checkpointer backend) changes between local dev/tests and deployed
  dev/prod namespaces.
- Dietary-restriction enforcement is deterministic (rule engine), never left to the LLM.
- No automated test may make a live call to Spoonacular, the Shufersal/Rami Levy feeds, or
  the real retailer websites; use recorded fixtures and a controlled mock retailer site.
- Every task ends with a passing test suite and a commit — do not move to the next
  checkpoint with a red build.
- **Helm is allowed, but only for third-party Kubernetes add-ons** that ship an official,
  maintained chart (e.g. Prometheus/Grafana via `kube-prometheus-stack`, CP14) — charts must
  come from trusted/maintained repositories, and Helm values are version-controlled files
  under `infra/helm/<chart>/` (env-specific values may be split, e.g. `dev-values.yaml` /
  `prod-values.yaml`). Helm is optional everywhere else: app-specific Kubernetes resources
  (backend, MCP servers, web, Postgres, Ingress) stay as plain manifests under `k8s/dev` /
  `k8s/prod`, unchanged. Introducing Helm does not change the existing NGINX Ingress design.
  Application metrics are exposed via `ServiceMonitor` resources (or another mechanism
  `kube-prometheus-stack` supports), not hand-rolled Prometheus scrape config.
- **Every checkpoint/plan is implemented in its own branch created from the latest `main`.**
  See "Git Branch Workflow" below for the concrete commands, branch lifecycle, and CI/CD
  triggers — every checkpoint's work begins by updating `main` and branching from it.

## Git Branch Workflow

Every implementation plan (each checkpoint, and any later fix/feature work) is completed in
its own branch, following the same lifecycle every time:

1. Switch to `main` and pull the latest remote `main` — **never** branch from `dev` or from
   a stale local `main`.
2. Create a new, descriptively-named branch from that up-to-date `main`, e.g.
   `feature/cp3-supermarket-mcp`, `feature/m2-recipe-flow`, `fix/ingestion-validation`.
3. Implement only that plan's scope in the new branch; commit as work progresses.
4. Run linting and the full relevant test suite locally before merging anywhere.
5. Switch to `dev`, pull the latest remote `dev`.
6. Merge the plan branch **directly into `dev`** (no Pull Request into `dev`) and push —
   this triggers the automatic dev pipeline (build/publish images, update dev manifests,
   deploy/sync the `dev` namespace).
7. Validate the feature in the deployed `dev` namespace.
8. Switch back to the **original plan branch** (do not delete it) and push it to the remote.
9. Open a Pull Request from that plan branch **directly into `main`** — `dev` is never merged
   into `main`.
10. Merge the Pull Request into `main` only after CI checks, review, and approval.
11. Production deployment/sync stays a separate, manual step performed after that merge.

```text
latest main
    ↓ create branch
plan branch
    ├── direct merge → dev
    │                     ↓
    │             automatic dev deployment
    │                     ↓
    │                  validation
    │
    └── push + Pull Request → main
                                 ↓
                         reviewed merge
                                 ↓
                    manual production deployment
                                 ↓
                                prod
```

**Concrete commands:**

```bash
git switch main
git pull origin main

git switch -c feature/<plan-name>

# Implement, test and commit the plan
git add .
git commit -m "feat: implement <plan-name>"

# Merge into dev for deployment and validation
git switch dev
git pull origin dev
git merge feature/<plan-name>
git push origin dev

# Return to the original plan branch
git switch feature/<plan-name>
git push -u origin feature/<plan-name>

# Open a Pull Request:
# feature/<plan-name> → main
```

**Rules/clarifications:**

- Every plan branch is created from the latest `main`, never from `dev`.
- There is no Pull Request into `dev` — the plan branch is merged directly into `dev` purely
  for deployment/validation.
- After validating in `dev`, work continues on the *same* original plan branch — a new branch
  is not created for the Pull Request into `main`.
- The Pull Request into `main` is opened from the plan branch, not from `dev`; `dev` itself is
  never merged into `main`.
- The plan branch must not be deleted until its Pull Request into `main` has been merged.
- A plan branch must never be created from an outdated local `main` — always `git pull origin
  main` immediately before branching.

**CI/CD behavior (see CP12, `docs/plan/12-github-actions-cicd.md`):**

- Work happens in a plan branch created from the latest `main`; lint + the full test suite
  run before that branch is merged into `dev`.
- A push to `dev` (from the direct merge) automatically builds/publishes images, updates the
  dev Kubernetes manifests, and deploys/syncs the `dev` namespace via ArgoCD.
- A Pull Request from a plan branch into `main` runs final lint/tests/validation as a required
  check.
- Merging that Pull Request into `main` creates/updates the production-ready version (images
  tagged off `main`, prod manifests updated) — it does **not** by itself deploy anything.
- Production ArgoCD sync/deployment remains a separate, manually-approved step performed after
  the merge into `main`.

**Acceptance checks per plan:**

- [ ] Branch was created from an up-to-date `main` (confirmed via `git pull origin main`
      immediately before `git switch -c`).
- [ ] Plan branch was merged directly into `dev` (no PR into `dev`) and `dev` was pushed.
- [ ] Dev CI/CD pipeline ran automatically off the `dev` push and the feature was validated in
      the deployed `dev` namespace.
- [ ] Work continued on the same original plan branch after validation (not a new branch).
- [ ] Plan branch was pushed to the remote and a Pull Request into `main` was opened from it.
- [ ] Pull Request checks (lint, full test suite) passed before merge.
- [ ] Merge into `main` was a reviewed/approved merge, not a direct push.
- [ ] Production deployment was a separate manual step, not triggered by the merge itself.
- [ ] The plan branch was not deleted before its Pull Request into `main` was merged.

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
| CP8 | Retailer-Cart MCP server (Playwright) | `docs/plan/08-playwright-cart-automation.md` | M3 |
| CP9 | Containerization & docker-compose | `docs/plan/09-containerization.md` | M4 |
| CP10 | Terraform + kubeadm cluster on EC2 | `docs/plan/10-terraform-kubeadm-cluster.md` | M4 |
| CP11 | ArgoCD GitOps bootstrap & dev deployment | `docs/plan/11-argocd-gitops-dev.md` | M4 |
| CP12 | GitHub Actions CI/CD pipeline | `docs/plan/12-github-actions-cicd.md` | M5 |
| CP13 | Production namespace & promotion flow | `docs/plan/13-prod-namespace-promotion.md` | M5 |
| CP14 | Prometheus & Grafana monitoring | `docs/plan/14-monitoring-prometheus-grafana.md` | M5 |
| CP15 | Test suite hardening & demo resilience | `docs/plan/15-test-hardening-resilience.md` | M6 |
| CP16 | UI polish, docs & final demo readiness | `docs/plan/16-ui-polish-docs-demo.md` | M6 |

## Deliverables

By the end of CP5 (M1): a runnable, tested, local-only system that turns a direct
grocery-list request into **two independent proposed carts** (one per retailer), with
clarification on ambiguous items and budget status/trade-offs shown for each, over a minimal
chat UI that lets the user choose one or decline.

By the end of CP7 (M2): the same system additionally accepts recipe requests, extracts and
scales ingredients via the Recipe MCP server, and enforces dietary constraints (substitution
or clear flagging) independently within each retailer's cart.

By the end of CP8 (M3): once the user chooses a retailer, the system opens that retailer's
site via Playwright, searches for and adds its cart's items, stops before checkout/login/
payment, handles partial per-item failures gracefully, and reports blocked automation
(CAPTCHA/bot-detection/login-wall) as a clean partial result — verified against a controlled
mock retailer site in automated tests.

By the end of CP11 (M4): the full stack (including the Retailer-Cart MCP server) runs in the
`dev` namespace of a kubeadm cluster on AWS EC2 (provisioned by Terraform), deployed via
ArgoCD, ingesting real Shufersal/Rami Levy feeds on a schedule, backed by PostgreSQL and a
DynamoDB checkpointer.

By the end of CP14 (M5): every plan branch is linted and tested (including mock-site
browser-automation tests) before merging directly into `dev`, whose push automatically builds
images and deploys `dev`; a Pull Request from the plan branch into `main` runs final
tests/validation, and `prod` exists as a separate namespace reachable only through a reviewed
merge into `main` followed by a manually-synced promotion; Prometheus/Grafana (installed via
the `kube-prometheus-stack` Helm chart) show live operational metrics, including
retailer-cart preparation success/failure/blocked rates.

By the end of CP16 (M6): the full test suite (unit, integration, contract, agent/graph,
ingestion, concurrency, Postgres-compatibility, mock-site browser automation) passes in CI,
the UI clearly surfaces clarifications/the two-cart comparison/real-cart results/warnings,
and the project is demo-ready end-to-end — including a live (manually verified) walkthrough
of real-site cart preparation as best-effort.

## Files Created/Modified (module map)

```
app/
  agent/           # LangGraph graph, nodes, state, checkpointer config      (CP4, CP7, CP8)
  dietary/         # deterministic dietary rule engine                       (CP7)
  db/
    models.py      # SQLAlchemy: RetailerProduct, RetailerFeedStatus          (CP2)
    repositories.py# repository layer used by MCP server + ingestion         (CP2)
    session.py     # DATABASE_URL-driven engine/session setup                (CP2)
  ingestion/       # feed download, parse, validate, atomic staging load     (CP2, CP15)
  api/             # FastAPI app, routes, request/response schemas           (CP5, CP8)
mcp_servers/         # each an independent HTTP service (own port, own container/Deployment)
  recipe_mcp/      # Recipe MCP server (Spoonacular), port 8002              (CP6)
  supermarket_mcp/ # Supermarket-Data MCP server (per-retailer only), 8001   (CP3)
  retailer_cart_mcp/ # Retailer-Cart MCP server (Playwright), port 8003      (CP8)
web/               # React chat SPA                                        (CP5, CP8, CP16)
infra/
  terraform/       # EC2 + kubeadm cluster provisioning                     (CP10)
  helm/            # version-controlled Helm values for third-party charts
    kube-prometheus-stack/
      dev-values.yaml  # dev-namespace values (Prometheus/Grafana)          (CP14)
      prod-values.yaml # prod-namespace values (Prometheus/Grafana)         (CP14)
k8s/
  dev/             # ArgoCD-watched dev namespace manifests, one Deployment/
                   # Service per MCP server + backend + web + postgres      (CP11)
  prod/            # ArgoCD-watched prod namespace manifests (same shape)   (CP13)
  argocd/          # ArgoCD install + Application manifests (incl. an
                   # Application pointing at the kube-prometheus-stack
                   # Helm chart + infra/helm values, per env)               (CP11, CP14)
  monitoring/      # any ServiceMonitor/PrometheusRule/dashboard resources
                   # layered on top of the Helm-installed stack — raw
                   # Prometheus/Grafana manifests are not maintained here   (CP14)
.github/workflows/ # CI/CD pipeline definitions                            (CP12)
tests/             # unit, integration, contract, agent, ingestion,
                   # mock-site browser-automation tests                    (all checkpoints)
Dockerfile           # shared image: backend, supermarket-mcp, recipe-mcp,
                     # ingestion (different `command:` per service)         (CP9)
Dockerfile.retailer-cart-mcp # separate image (needs Playwright browsers)   (CP9)
docker-compose.yml   # local dev stack — 4 backend-side services + web      (CP9)
```

## Task Checklists

- [x] CP1 — Project scaffolding & local dev environment
- [x] CP2 — Data model, database layer & ingestion pipeline
- [ ] CP3 — Supermarket-Data MCP server
- [ ] CP4 — LangGraph agent — grocery-list core flow
- [ ] CP5 — FastAPI backend & React chat UI
- [ ] CP6 — Recipe MCP server
- [ ] CP7 — Recipe flow integration & dietary rule engine
- [ ] CP8 — Retailer-Cart MCP server (Playwright)
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
| Independent per-retailer cart optimization (no cross-retailer product matching required) | CP2, CP3, CP4 |
| Budget as a first-class, best-effort optimization constraint with approved trade-offs | CP4 |
| Recipe requests via recipe API through custom MCP tool | CP6, CP7 |
| Prepares the retailer's online cart but never proceeds to checkout, payment, or order submission | CP8 |
| Real cart preparation only after the user chooses a retailer | CP4, CP8 |
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

**Definition of "project complete":** all 16 checkpoints are checked off, each implemented per
the Git Branch Workflow above; the full automated test suite (unit, integration, MCP
contract, agent/graph, ingestion, concurrent-thread-id, PostgreSQL-compatibility, mock-site
browser-automation) passes in CI on `main`; the `dev` namespace auto-deploys on every push to
`dev` and is currently healthy; the `prod` namespace has at
least one manually-promoted, working deployment; Prometheus/Grafana dashboards are live and
show real traffic from a demo run, including retailer-cart-preparation metrics; and a full
walkthrough of `docs/spec.md` §12 (Acceptance Criteria) passes manually against the deployed
`prod` namespace as the final demo script — including one live (best-effort, manually
observed) real-site cart preparation against an actual Shufersal or Rami Levy product.
