# CP12 — GitHub Actions CI/CD Pipeline

Spec milestone: M5 (starts). Depends on: CP9, CP11.

> **As-built note (2026-08-11):** implemented as a structural migration of a separate,
> already-working infrastructure project (`polyaifursa`)'s `cd.yml` (paths-filter build
> matrix + manifest-bump pattern), adapted to this project's six real services. The original
> design below (a single shared `Dockerfile` + Alembic/PostgreSQL compatibility gate) was
> never implemented as written — this project has six separate per-service Dockerfiles
> (CP9), and the Postgres/Alembic plan was superseded (see CP11's as-built note: the app
> runs on SQLite/in-memory checkpointing, not Postgres).

## Goal

Wire up the existing lint+test CI (`ci.yml`, already in place ahead of this checkpoint — see
below) and a new CD pipeline (`cd.yml`) that builds and pushes per-service, Git-SHA-tagged
images and bumps the matching `infra/k8s/{dev,prod}/` manifest on every push to `dev`/`main`,
which ArgoCD's `dev`/`prod` Applications (CP11) then pick up.

## `ci.yml` (already existed before this checkpoint)

Runs on every PR/push to `main`: Python setup, `make install`, `ruff check`, `pytest` with
coverage, Codecov upload. Unchanged by this checkpoint — no Postgres service container was
ever added (no Postgres exists to compatibility-check), no coverage-threshold gate.

## `cd.yml` (new)

```
detect (dorny/paths-filter)  -->  build (matrix, 6 services)  -->  update-manifests
```

- **`detect`** — `dorny/paths-filter` against `github.event.before`..`github.sha`, one
  filter per service: `backend` (`app/agent/**`, `app/api/**`, `app/dietary/**`), `web`
  (`web/**`), `supermarket_mcp` (`mcp_servers/supermarket_mcp/**`, `app/db/**`), `recipe_mcp`
  (`mcp_servers/recipe_mcp/**`), `retailer_cart_mcp` (`mcp_servers/retailer_cart_mcp/**`),
  `ingestion` (`app/ingestion/**`, `app/db/**`, `tests/fixtures/feeds/**`). `app/db/**` is
  listed under both `supermarket_mcp` and `ingestion` since both Dockerfiles `COPY` it.
- **`build`** — a 6-way matrix (`backend`, `web`, `supermarket-mcp`, `recipe-mcp`,
  `retailer-cart-mcp`, `ingestion`), each building `context: .` with its own `dockerfile:`
  path (matching `docker-compose.yml`'s own convention — every Dockerfile here `COPY`s
  shared modules like `app/db`, so a per-service subdirectory context wouldn't work), pushed
  to Docker Hub as `<image>:${{ github.sha }}` only when that service's `detect` output is
  `true`.
- **`update-manifests`** — picks `ENV_DIR=dev` or `prod` from the branch, `sed`-replaces each
  changed service's `image:` line in `infra/k8s/${ENV_DIR}/<service>/*.yaml` with the new
  SHA tag, and pushes the commit with the default `GITHUB_TOKEN` (not a PAT) — GitHub does
  not trigger new workflow runs for pushes made with the default token, so this commit does
  not re-trigger CI/CD and cause a loop. Six images, six possible manifest files
  (`ingestion` bumps `ingestion-cronjob.yaml`, the rest bump `*-deployment.yaml`).

## `sync-retailer-sessions.yml` (new, see CP11)

Not a build/deploy workflow — keeps the `retailer-cart-sessions` Kubernetes Secret current
from GitHub Secrets on every push. Documented in full under CP11.

## `cluster.yaml` (new, see CP10)

`workflow_dispatch`-only (infrastructure changes are never applied automatically on a normal
push) — `terraform fmt -check` + `validate` + `plan` + `apply`, persists `CONTROL_PLANE_IP`
as a repo variable (needed since Terraform state is local — no other workflow run could
otherwise learn the cluster's address), renders `infra/k8s/monitoring/values.yaml` from
Terraform's SNS topic ARN output via `envsubst`, and bootstraps the cluster over SSH.

## Validation performed (code + static validation only)

- [x] `actionlint` on all four workflow files — clean except one expected, intentional
      shellcheck note on `cluster.yaml`'s `envsubst '${SNS_TOPIC_ARN}'` line (the single
      quotes are deliberate — `envsubst` needs the literal variable-list string, not a
      shell-expanded one; the identical line exists in the migrated reference
      infrastructure's own `cluster.yaml`).
- [x] Ruby `YAML.load_file` on all four workflow files — parse successfully.
- [x] `docker build` of the backend image (one of the six `cd.yml` would build) — succeeds,
      confirming the Dockerfile paths `cd.yml` references are correct.

## Risks

- `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`, `SSH_PRIVATE_KEY`, `DEPLOY_KEY`, and the four
  `RETAILER_SESSION_*` secrets must all be configured as GitHub repo secrets before any of
  these workflows can run end-to-end — none of that was done in this environment (code +
  static validation only), so `cd.yml`/`cluster.yaml`/`sync-retailer-sessions.yml` are
  untested against a real GitHub Actions run.
- `gh variable set` in `cluster.yaml` needs the default `GITHUB_TOKEN` to have "Read and
  write permissions" for Actions enabled (repo Settings → Actions → General), or a PAT in
  `secrets.VARS_PAT` as a documented fallback.

## Notes

CP13 reuses these same CI-built image tags for its promotion flow — no separate build step.

## Definition of Done

- [x] `ci.yml` unchanged and confirmed still passing (357 tests, ruff clean) after all of
      this checkpoint's application-side changes (Prometheus metrics instrumentation, CP14).
- [x] `cd.yml`, `cluster.yaml`, `sync-retailer-sessions.yml` created, statically validated.
- [x] Committed with message referencing CP12.
