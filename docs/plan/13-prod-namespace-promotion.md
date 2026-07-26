# CP13 — Production Namespace & Promotion Flow

Spec milestone: M5. Depends on: CP11, CP12.

## Goal

Populate `k8s/prod/` with a full, isolated set of resources (mirroring `k8s/dev/`, but its
own namespace, secrets, and storage), and establish the manual promotion flow: copy the
exact, already-validated image tags from `k8s/dev/` into `k8s/prod/` via a reviewed PR, then
trigger a manual ArgoCD sync — so production only ever changes through a deliberate,
reviewed action, never automatically.

## Scope

`k8s/prod/` manifests and the promotion script/process. No changes to `k8s/dev/`, CI, or
ArgoCD `Application` definitions (those are already correct from CP11/CP12).

## Deliverables

- `k8s/prod/` fully deployed: backend, web, Postgres, ingestion CronJob, all running in
  `supermarket-prod`, isolated from `supermarket-dev`.
- A documented, scripted promotion flow: run a script, review the resulting diff, open a
  PR, merge, then manually sync — never an automatic prod deployment.

## Files to Create

```
k8s/prod/secret.env.example
k8s/prod/postgres-pv.yaml
k8s/prod/postgres-statefulset.yaml
k8s/prod/postgres-service.yaml
k8s/prod/backend-deployment.yaml
k8s/prod/backend-service.yaml
k8s/prod/web-deployment.yaml
k8s/prod/web-service.yaml
k8s/prod/ingestion-cronjob.yaml
scripts/promote_to_prod.sh
```

## Detailed Implementation Steps

1. Copy each `k8s/dev/*.yaml` manifest (from CP11) into the corresponding `k8s/prod/*.yaml`
   file, changing: `namespace: supermarket-dev` → `supermarket-prod`; the Postgres
   `hostPath` to a distinct directory (`/var/lib/supermarket-assistant/postgres-prod`, not
   the dev path, so the two environments never share storage even though they run on the
   same physical worker node); and the image tags left as **placeholders** initially — they
   get filled in by the promotion script (step 3), never hand-typed.
2. Create the prod secret (manual, one-time, not committed): `kubectl -n supermarket-prod
   create secret generic app-secrets --from-env-file=k8s/prod/secret.env` (a local,
   gitignored copy of `k8s/prod/secret.env.example` with prod-appropriate values — the
   `SPOONACULAR_API_KEY` may be shared with dev; `POSTGRES_PASSWORD` should not be).
3. Write `scripts/promote_to_prod.sh`, which reads the currently-deployed image tags out of
   `k8s/dev/` and writes those exact tags into `k8s/prod/` — this is what makes promotion
   "copy the exact validated tags," not a fresh build:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail

   BACKEND_TAG=$(grep -oP '(?<=supermarket-backend:)[a-zA-Z0-9._-]+' k8s/dev/backend-deployment.yaml | head -1)
   WEB_TAG=$(grep -oP '(?<=supermarket-web:)[a-zA-Z0-9._-]+' k8s/dev/web-deployment.yaml | head -1)

   sed -i "s|supermarket-backend:.*|supermarket-backend:${BACKEND_TAG}|" \
     k8s/prod/backend-deployment.yaml k8s/prod/ingestion-cronjob.yaml
   sed -i "s|supermarket-web:.*|supermarket-web:${WEB_TAG}|" k8s/prod/web-deployment.yaml

   echo "Promoted backend=${BACKEND_TAG} web=${WEB_TAG} into k8s/prod/."
   echo "Review with 'git diff k8s/prod', then open a PR — do not push directly to main."
   ```
   `chmod +x scripts/promote_to_prod.sh`.
4. Run the script once with whatever tag is currently live in `k8s/dev/` after CP12's
   pipeline has run at least once; `git diff k8s/prod` to review the change.
5. Open a PR with just the `k8s/prod/` diff, get it reviewed (even if self-reviewed, solo),
   and merge to `main`.
6. Trigger the manual ArgoCD sync for the prod `Application` (CLI: `argocd app sync
   supermarket-assistant-prod`, or the equivalent button in the ArgoCD UI) — confirm nothing
   deploys to prod on its own before this step.
7. `kubectl -n supermarket-prod get pods` — confirm backend, web, postgres, and the
   ingestion CronJob are all running.
8. Manually trigger one ingestion run in prod (same pattern as CP11 step 23) to populate
   prod's Postgres independently of dev's.
9. `curl` the prod NodePorts and manually walk through the full acceptance-criteria list
   from `docs/spec.md` §12 against this prod deployment — this doubles as the project's
   final demo script (per `docs/plan.md`'s Final Milestone).
10. Commit all `k8s/prod/` files and the promotion script (excluding the real
    `k8s/prod/secret.env`).

## Testing Tasks

- [ ] `k8s/prod/` resources all come up healthy after the first manual sync.
- [ ] Confirm merging the promotion PR to `main` does **not** by itself change anything in
      the `supermarket-prod` namespace — only the manual sync does.
- [ ] Full manual walkthrough of spec §12's acceptance criteria against prod.
- [ ] Confirm dev and prod Postgres data are independent (seeding one doesn't affect the
      other).

## Acceptance Criteria

Production runs the same validated images already running in dev, in a fully isolated
namespace, and only ever changes as the result of a reviewed PR followed by an explicit
manual sync — never automatically.

## Risks

- Both namespaces currently share the **same** DynamoDB checkpoint table (from CP11) —
  acceptable because `thread_id` is a random UUID with effectively no cross-environment
  collision risk, and provisioning a second table/checkpointer config per environment was
  judged not worth the added Terraform complexity for a solo MVP. Revisit if this ever
  becomes a real concern.
- Both namespaces' Postgres pods are `hostPath`-pinned to the same single worker node (per
  CP11's simplification) — a worker node failure takes down both dev and prod storage
  simultaneously. Acceptable for MVP scope; noted as a real production concern if this were
  ever more than a course project.

## Notes

Do not add an `automated:` sync policy to the prod `Application` at any point — that would
silently reintroduce automatic production deployments and contradict spec §7's explicit
manual-promotion requirement.

## Definition of Done

- [ ] `k8s/prod/` manifests and `scripts/promote_to_prod.sh` created.
- [ ] First promotion executed end-to-end (script → PR → merge → manual sync → verified
      running).
- [ ] Full spec §12 acceptance-criteria walkthrough passes manually against prod.
- [ ] Committed with message referencing CP13.
