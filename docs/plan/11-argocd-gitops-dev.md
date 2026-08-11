# CP11 — ArgoCD GitOps Bootstrap & Dev Deployment

Spec milestone: M4 (completes M4). Depends on: CP9, CP10.

> **As-built note (2026-08-11):** implemented as a structural migration of a separate,
> already-working infrastructure project (`polyaifursa`)'s ArgoCD App-of-Apps pattern, not
> designed from scratch. The original design below (a single `dev-application.yaml` /
> `prod-application.yaml` pair, `k8s/dev/` at the repo root, Postgres + DynamoDB) was never
> implemented as written — see "Actual Architecture."

## Goal

Install ArgoCD onto the kubeadm cluster (one-time bootstrap via `scripts/bootstrap.sh`), and
have it continuously reconcile the `dev` namespace's Kubernetes resources from Git — so a
push to the `dev` branch flows through to a running dev deployment without any manual
`kubectl apply` after this checkpoint.

## Actual Architecture

**ArgoCD install:** `scripts/bootstrap.sh` (copied onto the control-plane node and run once
by `.github/workflows/cluster.yaml`, or by hand) waits for the API server, installs Calico
(left commented out of `control-plane.sh` deliberately — see CP10), the metrics-server
(patched with `--kubelet-insecure-tls`, since this cluster's kubelets don't have
CA-signed serving certs), the AWS EBS CSI driver (needed for the `ebs-sc` StorageClass that
`supermarket-mcp`'s SQLite volume and `kube-prometheus-stack`'s PVCs use), then ArgoCD itself
(`argocd-server` patched to `server.insecure: true` — TLS terminates at the ALB, not at
ArgoCD, so plain-HTTP behind ingress-nginx is correct here, not a security gap), and finally
applies `infra/argocd/app-of-apps.yaml`.

**App-of-Apps (`infra/argocd/`):** one root `Application` (`app-of-apps.yaml`, tracking
`HEAD` on this same repo, `directory.recurse: true` over `infra/argocd/`) discovers and
applies every other `Application` in that same directory:

| Application | Path | `targetRevision` | Sync policy |
|---|---|---|---|
| `cluster-resources` | `infra/k8s/common` | `main` | automated, prune+selfHeal |
| `dev` | `infra/k8s/dev` | `dev` branch | automated, prune+selfHeal |
| `prod` | `infra/k8s/prod` | `main` | **manual only** — no `automated:` block |
| `ingress-nginx` | Helm chart `ingress-nginx/ingress-nginx` + `infra/helm/ingress-nginx-values.yaml` | `main` | automated, prune+selfHeal |
| `monitoring` | Helm chart `kube-prometheus-stack` + `infra/k8s/monitoring/values.yaml` | `main` | automated, prune+selfHeal, `ServerSideApply=true` |

`dev` tracking the `dev` git branch directly (rather than `main` with a separate promotion
step) means every merge into `dev` — the normal end of this project's own git workflow — is
what deploys to the dev namespace; no separate "apply once, then GitOps takes over" bootstrap
step is needed for application manifests, only for ArgoCD itself.

**`infra/k8s/dev/` (six services, mirroring CP9's six Dockerfiles exactly):**

- `backend/` — Deployment + Service + HPA (1-3 replicas, CPU 50%) + Ingress (`/api` routed
  from `supermarket-dev.<zone>`) + ServiceMonitor (`/metrics`, 15s).
- `web/` — Deployment + Service + HPA + Ingress (`/` on the same host).
- `supermarket-mcp/` — Deployment + Service + a PVC (`ebs-sc`, 2Gi, `ReadWriteOnce`) mounted
  at `/data` for its SQLite database. Fixed at 1 replica, no HPA — SQLite doesn't support
  safe concurrent writers across pods.
- `recipe-mcp/` — Deployment + Service. `SPOONACULAR_API_KEY` comes from a
  `recipe-mcp-secrets` Kubernetes Secret (see "Secrets," below).
- `retailer-cart-mcp/` — Deployment + Service, bumped resource requests/limits (Playwright's
  Chromium is the only real per-request browser workload in this project). Session cookies
  mount from a `retailer-cart-sessions` Secret at `/app/sessions` (see "Secrets," below).
- `ingestion/` — a **CronJob** (`schedule: "0 3 * * *"`, `concurrencyPolicy: Forbid`), never
  a Deployment, sharing `supermarket-mcp`'s PVC.

`infra/k8s/prod/` is byte-for-byte the same files, differing only in `namespace: prod`,
hostname, and (once CI has run) image tag — see CP13.

**No Postgres, no DynamoDB checkpointer.** The originally-sketched design (a `postgres`
StatefulSet + a `dynamodb` LangGraph checkpointer backend) was never built: the app's actual,
current runtime configuration is `DATABASE_URL=sqlite:////data/app.db` (for `supermarket-mcp`
and `ingestion` only — the backend never touches SQLite directly) and
`CHECKPOINTER_BACKEND=memory` (`app/agent/checkpointer.py` only implements `memory` and
`sqlite`; `dynamodb` raises `ValueError`). Introducing a real database migration is a
separate, application-layer change this infrastructure checkpoint deliberately does not
make — it was never requested and the app has no genuine need for it yet.

## Secrets (no committed values, no manual `kubectl create secret`)

- `recipe-mcp-secrets` (`SPOONACULAR_API_KEY`) — created by whatever process manages
  application secrets for this cluster (out of scope for this checkpoint; not automated by
  any workflow here).
- `retailer-cart-sessions` (`shufersal.json`, `rami_levy.json`) — **fully automated**:
  `.github/workflows/sync-retailer-sessions.yml` creates/updates this Secret in both `dev`
  and `prod` on every push, reading the raw session JSON from GitHub Secrets
  (`RETAILER_SESSION_SHUFERSAL_DEV`/`_PROD`, `RETAILER_SESSION_RAMI_LEVY_DEV`/`_PROD`) and
  applying it over SSH to the control plane. The session JSON never touches this repo (`git
  check-ignore sessions/` confirms the whole directory is gitignored) and is never baked into
  any Docker image — `mcp_servers/retailer_cart_mcp/RETAILER_SESSIONS_DIR` just points at the
  mounted Secret volume, so no application code changed. See "Retailer Session Secrets Setup"
  below for exactly what to configure.

## Retailer Session Secrets Setup

1. Produce fresh session files locally, exactly as before this infrastructure existed:
   `python -m mcp_servers.retailer_cart_mcp.login` (per-retailer, needs a real display) to
   produce `sessions/shufersal.json` / `sessions/rami_levy.json`.
2. In the GitHub repo's Settings → Secrets and variables → Actions, add:
   `RETAILER_SESSION_SHUFERSAL_DEV`, `RETAILER_SESSION_RAMI_LEVY_DEV`,
   `RETAILER_SESSION_SHUFERSAL_PROD`, `RETAILER_SESSION_RAMI_LEVY_PROD` — each containing the
   full raw contents of the matching JSON file (paste the file's text as the secret value).
   Dev and prod are separate secrets on purpose: Kubernetes Secrets are namespace-scoped, and
   this lets dev/prod use different retailer logins if ever needed (using the same real
   account's session in both is also fine — just paste the same content into both secrets).
3. Also add `CONTROL_PLANE_IP` is **not** a secret you set — `.github/workflows/cluster.yaml`
   sets it automatically as a repo *variable* after provisioning. `SSH_PRIVATE_KEY` (the
   key that can SSH to the control-plane node as `ubuntu`) must be a repo secret for both
   `cluster.yaml` and `sync-retailer-sessions.yml` to work.
4. From here on, every push to `dev`/`main` (or a manual `workflow_dispatch` of
   `sync-retailer-sessions.yml`) keeps both namespaces' `retailer-cart-sessions` Secret in
   sync automatically. Rotating a stale/expired session is: repeat step 1, update the GitHub
   Secret's value, re-run the workflow (or just push) — no `kubectl` required.

## Validation performed (code + static validation only)

- [x] `kubeconform` (with the ArgoCD/prometheus-operator CRD schemas) — all 48 plain
      Kubernetes + `Application`/`ServiceMonitor`/`PrometheusRule` manifests under
      `infra/k8s/` and `infra/argocd/` validate successfully.
- [x] `helm template` of both third-party charts (`ingress-nginx`, `kube-prometheus-stack`)
      against this project's own values files — both render successfully.
- [x] `docker build` of the backend image + a live container smoke test (`/health`,
      `/metrics` both respond) — confirms the image CP11's Deployment references actually
      starts correctly.
- [x] `actionlint` on `sync-retailer-sessions.yml` — clean.

## Risks

- No cluster was actually bootstrapped in this environment (code + static validation only,
  per the same product decision as CP10) — ArgoCD's actual sync behavior, the
  `retailer-cart-sessions` Secret sync over SSH, and the EBS CSI driver's PVC binding are all
  unverified against a real cluster. Everything up to that boundary (manifest correctness,
  Helm chart compatibility, image builds) is verified.
- `recipe-mcp-secrets` has no automated creation path (unlike `retailer-cart-sessions`) —
  document this as a manual one-time step until/unless it's worth automating the same way.

## Definition of Done

- [x] `infra/argocd/`, `infra/k8s/common/`, `infra/k8s/dev/`, `infra/k8s/prod/` created and
      validated.
- [x] `scripts/bootstrap.sh` adapted, `sync-retailer-sessions.yml` created.
- [x] Committed with message referencing CP11. **M4 milestone complete at this point** (code
      + static validation; live cluster verification deferred per the product decision above).
