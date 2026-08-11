# CP13 — Production Namespace & Promotion Flow

Spec milestone: M5. Depends on: CP11, CP12.

> **As-built note (2026-08-11):** implemented as a structural migration of a separate,
> already-working infrastructure project (`polyaifursa`)'s branch-based promotion model
> (ArgoCD's `prod` Application tracks the `main` git branch directly), not the
> script-driven, path-copying design originally sketched below. No `scripts/promote_to_prod.sh`
> was written — this architecture doesn't need one; promotion is a plain git merge.

## Goal

Populate `infra/k8s/prod/` with a full, isolated set of resources (mirroring
`infra/k8s/dev/`, same six services, own namespace), and establish the promotion flow: a
push to `main` (via this project's own established git workflow — PR from a plan branch
directly into `main`) is what makes new image tags land in `infra/k8s/prod/`, but nothing in
the `prod` namespace changes until someone explicitly triggers an ArgoCD sync — so production
only ever changes through a deliberate, reviewed action, never automatically.

## Actual Architecture

`infra/k8s/prod/` mirrors `infra/k8s/dev/`'s six services (`backend`, `web`,
`supermarket-mcp`, `recipe-mcp`, `retailer-cart-mcp`, `ingestion`), differing in
`namespace: prod`, the `supermarket-prod.<zone>` hostname, image tags (once CI has run at
least once), and — per an explicit later decision — the data backend: prod's `backend` sets
`CHECKPOINTER_BACKEND=dynamodb` (dev: `memory`) and prod's `supermarket-mcp`/`ingestion` read
`DATABASE_URL` from the `postgres-credentials` Secret pointing at an in-cluster Postgres
StatefulSet (dev: a local SQLite PVC) — see CP11's "Prod-only: Postgres + DynamoDB" for the
full architecture and rationale. `infra/k8s/prod/` also has one directory `infra/k8s/dev/`
doesn't: `postgres/` (the StatefulSet + headless Service). `infra/argocd/prod.yaml`'s
`Application` tracks `targetRevision: main` at `path: infra/k8s/prod`, with **no
`automated:` sync block** — only `syncOptions: [CreateNamespace=true]`. Compare
`infra/argocd/dev.yaml`, which tracks the `dev` branch with
`automated: {prune: true, selfHeal: true}`.

**Promotion flow, concretely:**

1. A plan/fix branch merges into `dev` (this project's normal workflow) — `dev`'s
   Application auto-syncs, deploying to the `dev` namespace immediately.
2. The same branch's PR merges into `main` (also this project's normal workflow) —
   `.github/workflows/cd.yml`'s `update-manifests` job runs again, this time bumping
   `infra/k8s/prod/<service>/*.yaml` to the new commit's SHA-tagged images (the images
   themselves were already built and pushed by the same job, tagged by commit SHA
   regardless of branch).
3. `infra/k8s/prod/`'s new image tags now sit in `main`, but the `prod` Application has no
   automated sync policy, so nothing in the cluster changes yet.
4. A human explicitly runs `argocd app sync prod` (CLI) or clicks Sync in the ArgoCD UI —
   only then does production actually change.

No separate promotion script, no manual `sed`/tag-copying step, and no separate PR just for
`infra/k8s/prod/` — the existing "PR into `main`" step in this project's established git
workflow (`docs/plan.md`'s "Git Branch Workflow") already is the promotion review gate; step
4 above is the only production-specific manual action.

## Secrets

`recipe-mcp-secrets` (manual, not automated) and `retailer-cart-sessions` (fully automated
via `sync-retailer-sessions.yml`, using the `RETAILER_SESSION_*_PROD` GitHub Secrets — see
CP11's "Retailer Session Secrets Setup") exist in both namespaces. `postgres-credentials`
(manual, not automated — see CP11) exists in `prod` only, since `dev` has no Postgres.

## Validation performed (code + static validation only)

- [x] `kubeconform` — all 18 `infra/k8s/prod/*.yaml` manifests (incl.
      `postgres-statefulset.yaml`/`postgres-service.yaml`) validate successfully.
- [x] Confirmed `infra/argocd/prod.yaml` has no `automated:` key (manual-only sync), unlike
      every other `Application` in `infra/argocd/`.
- [x] Live Postgres smoke test (see CP11) confirms prod's `supermarket-mcp`/`ingestion`
      `DATABASE_URL` wiring actually works against a real Postgres, not just that the
      manifests parse.

## Risks

- No cluster was actually bootstrapped in this environment — the real promotion flow (steps
  1-4 above) is unverified against a live ArgoCD instance. The manifest structure and sync
  policy are verified statically.
- Prod's data is genuinely isolated from dev's: dev's `supermarket-mcp` uses its own SQLite
  PVC (`supermarket-mcp-data`) and the in-memory LangGraph checkpointer (nothing persisted
  between pod restarts); prod uses its own Postgres StatefulSet PVC and the one DynamoDB
  checkpoint table Terraform provisions — dev never touches either, so there's no
  shared-storage collision risk to reason about at all (unlike the original CP13 sketch's own
  shared-DynamoDB-table trade-off, which doesn't apply here).

## Notes

Do not add an `automated:` sync policy to `infra/argocd/prod.yaml` at any point — that would
silently reintroduce automatic production deployments and contradict spec §7's explicit
manual-promotion requirement.

## Definition of Done

- [x] `infra/k8s/prod/` created (18 manifests: mirrors `infra/k8s/dev/`'s six services, plus
      `postgres/`, which `infra/k8s/dev/` doesn't have).
- [x] `infra/argocd/prod.yaml` confirmed manual-sync-only.
- [x] Committed with message referencing CP13.
