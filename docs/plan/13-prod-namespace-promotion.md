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

`infra/k8s/prod/` is byte-for-byte the same file layout as `infra/k8s/dev/` (six services:
`backend`, `web`, `supermarket-mcp`, `recipe-mcp`, `retailer-cart-mcp`, `ingestion`),
differing only in `namespace: prod`, the `supermarket-prod.<zone>` hostname, and (once CI has
run at least once) image tags. `infra/argocd/prod.yaml`'s `Application` tracks `targetRevision:
main` at `path: infra/k8s/prod`, with **no `automated:` sync block** — only
`syncOptions: [CreateNamespace=true]`. Compare `infra/argocd/dev.yaml`, which tracks the
`dev` branch with `automated: {prune: true, selfHeal: true}`.

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

Same as `dev` (CP11): `recipe-mcp-secrets` (manual, not automated) and
`retailer-cart-sessions` (fully automated via `sync-retailer-sessions.yml`, using the
`RETAILER_SESSION_*_PROD` GitHub Secrets — see CP11's "Retailer Session Secrets Setup").

## Validation performed (code + static validation only)

- [x] `kubeconform` — all 17 `infra/k8s/prod/*.yaml` manifests validate successfully
      (included in CP11's 48-manifest validation run).
- [x] `diff` confirms `infra/k8s/dev/` and `infra/k8s/prod/` differ only in `namespace` and
      hostname (image tags identical placeholder `:latest` in both, since neither has had a
      real CI run yet).
- [x] Confirmed `infra/argocd/prod.yaml` has no `automated:` key (manual-only sync), unlike
      every other `Application` in `infra/argocd/`.

## Risks

- No cluster was actually bootstrapped in this environment — the real promotion flow (steps
  1-4 above) is unverified against a live ArgoCD instance. The manifest structure and sync
  policy are verified statically.
- Both namespaces' `supermarket-mcp` SQLite data are on separate PVCs (`supermarket-mcp-data`
  in each namespace) — genuinely isolated, unlike the reference infrastructure's shared
  `hostPath` trade-off the original CP13 sketch inherited.

## Notes

Do not add an `automated:` sync policy to `infra/argocd/prod.yaml` at any point — that would
silently reintroduce automatic production deployments and contradict spec §7's explicit
manual-promotion requirement.

## Definition of Done

- [x] `infra/k8s/prod/` created (17 manifests, mirroring `infra/k8s/dev/`).
- [x] `infra/argocd/prod.yaml` confirmed manual-sync-only.
- [x] Committed with message referencing CP13.
