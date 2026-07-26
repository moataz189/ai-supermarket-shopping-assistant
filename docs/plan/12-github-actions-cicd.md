# CP12 — GitHub Actions CI/CD Pipeline

Spec milestone: M5 (starts). Depends on: CP9, CP11.

## Goal

Wire up the CI pipeline (lint, full test suite including a real-PostgreSQL compatibility
check, on every PR) and the CD pipeline (build + push immutably-tagged images, bump
`k8s/dev/` image tags on merge to `main`) that ArgoCD's dev `Application` (CP11) picks up
automatically.

## Scope

GitHub Actions workflows, Alembic migration setup (retrofitting CP2's SQLAlchemy models into
versioned migrations so there's something meaningful for the Postgres compatibility check to
run), and the manifest-bump mechanics. Does not touch `k8s/prod/` (CP13).

## Deliverables

- Every PR runs lint + the full test suite (including a job that runs migrations and a
  smoke query against a real PostgreSQL service container) and must pass before merge.
- Every merge to `main` builds and pushes Git-SHA-tagged images for the backend and web
  services, then commits the new tags into `k8s/dev/`, which ArgoCD auto-syncs.

## Files to Create

```
.github/workflows/ci.yml
.github/workflows/build-and-deploy-dev.yml
migrations/env.py
migrations/versions/0001_initial.py
alembic.ini
tests/db/test_postgres_compatibility.py
```

## Files to Modify

- `app/db/session.py` — no functional change, but confirm it still reads `DATABASE_URL` the
  same way now that schema creation goes through Alembic instead of `Base.metadata.create_all`.
- `pyproject.toml` — add `alembic` and `psycopg[binary]` dependencies.

## Detailed Implementation Steps

### Alembic retrofit (needed for a meaningful Postgres compatibility check)

1. `pip install alembic psycopg[binary]`; add both to `pyproject.toml`.
2. `alembic init migrations` from the repo root; edit `alembic.ini`'s
   `sqlalchemy.url` to read from the `DATABASE_URL` environment variable at runtime instead
   of a hardcoded value (set it to a placeholder and override in `migrations/env.py`).
3. Edit `migrations/env.py` to import `app.db.models.Base` and set `target_metadata =
   Base.metadata`, and to read the connection URL via `os.environ["DATABASE_URL"]`.
4. Generate the initial migration from CP2's existing models:
   `alembic revision --autogenerate -m "initial"`; review the generated
   `migrations/versions/0001_initial.py` against `app/db/models.py`'s
   `CanonicalProduct`/`RetailerOffer`/`RetailerFeedStatus` tables and fix anything the
   autogenerate step got wrong (index names, nullability).
5. Run `alembic upgrade head` against local SQLite and confirm the schema matches what CP2's
   ad-hoc table creation produced; run the CP2 test suite against it to confirm nothing
   broke.

### CI workflow

6. Write `.github/workflows/ci.yml`:
   ```yaml
   name: CI

   on:
     pull_request:
       branches: [main]
     push:
       branches: [main]

   jobs:
     lint-and-test:
       runs-on: ubuntu-latest
       services:
         postgres:
           image: postgres:16
           env:
             POSTGRES_USER: app
             POSTGRES_PASSWORD: app
             POSTGRES_DB: supermarket_test
           ports: ["5432:5432"]
           options: >-
             --health-cmd="pg_isready -U app"
             --health-interval=5s --health-timeout=5s --health-retries=10
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.11"
         - run: pip install -e ".[dev]"
         - run: playwright install --with-deps chromium
         - run: ruff check app tests mcp_servers
         - name: Unit, integration, MCP contract, agent, and mock-site browser-automation tests
           run: pytest --maxfail=1
           env:
             DATABASE_URL: sqlite:///./app.db
             CHECKPOINTER_BACKEND: memory
         - name: PostgreSQL migration & compatibility check
           run: |
             alembic upgrade head
             pytest tests/db/test_postgres_compatibility.py -v
           env:
             DATABASE_URL: postgresql+psycopg://app:app@localhost:5432/supermarket_test
   ```
7. Write `tests/db/test_postgres_compatibility.py` — runs the same `ProductRepository`
   operations from CP2's tests, but against the real Postgres service container instead of
   SQLite, to catch SQLite-only-compatible queries:
   ```python
   import os

   import pytest
   from sqlalchemy import create_engine
   from sqlalchemy.orm import sessionmaker

   from app.db.models import CanonicalProduct, RetailerOffer
   from app.db.repositories import ProductRepository

   pytestmark = pytest.mark.skipif(
       "postgresql" not in os.environ.get("DATABASE_URL", ""),
       reason="only meaningful against a real PostgreSQL instance",
   )


   def test_search_and_offer_aggregation_against_postgres():
       engine = create_engine(os.environ["DATABASE_URL"])
       Session = sessionmaker(bind=engine)
       with Session() as session:
           session.add(
               CanonicalProduct(
                   product_id="p1", barcode="123", name="Milk 1L", category="dairy",
                   package_size=1.0, package_unit="l",
               )
           )
           session.add(RetailerOffer(
               product_id="p1", retailer="shufersal", branch_id="b1",
               retailer_product_code="rp1", price=6.9, listed_in_feed=True,
               last_updated_at=__import__("datetime").datetime.now(),
           ))
           session.commit()

           repo = ProductRepository(session)
           assert repo.search_candidates("Milk")
           offers = repo.get_offers_by_retailer("p1")
           assert offers["shufersal"].price == 6.9
   ```
8. Run this locally against a `docker run -p 5432:5432 -e POSTGRES_PASSWORD=app -e
   POSTGRES_USER=app -e POSTGRES_DB=supermarket_test postgres:16` container to confirm it
   passes before relying on CI to catch issues.

### CD workflow

9. Write `.github/workflows/build-and-deploy-dev.yml` — builds and pushes immutable,
   Git-SHA-tagged images, then bumps `k8s/dev/`'s image references. The manifest-bump commit
   is pushed using the workflow's default `GITHUB_TOKEN` (not a personal access token) —
   GitHub does not trigger new workflow runs for pushes made with the default token, so this
   commit does not re-trigger CI/CD and cause a loop:
   ```yaml
   name: Build and Deploy Dev

   on:
     push:
       branches: [main]

   jobs:
     build-and-push:
       runs-on: ubuntu-latest
       outputs:
         sha: ${{ steps.sha.outputs.sha }}
       steps:
         - uses: actions/checkout@v4
         - id: sha
           run: echo "sha=$(git rev-parse --short HEAD)" >> "$GITHUB_OUTPUT"
         - uses: docker/login-action@v3
           with:
             username: ${{ secrets.DOCKERHUB_USERNAME }}
             password: ${{ secrets.DOCKERHUB_TOKEN }}
         - name: Build and push backend image
           run: |
             docker build -f Dockerfile.backend \
               -t ${{ secrets.DOCKERHUB_USERNAME }}/supermarket-backend:${{ steps.sha.outputs.sha }} .
             docker push ${{ secrets.DOCKERHUB_USERNAME }}/supermarket-backend:${{ steps.sha.outputs.sha }}
         - name: Build and push web image
           run: |
             docker build -f web/Dockerfile \
               -t ${{ secrets.DOCKERHUB_USERNAME }}/supermarket-web:${{ steps.sha.outputs.sha }} .
             docker push ${{ secrets.DOCKERHUB_USERNAME }}/supermarket-web:${{ steps.sha.outputs.sha }}

     update-dev-manifests:
       needs: build-and-push
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
           with:
             token: ${{ secrets.GITHUB_TOKEN }}
         - name: Bump image tags in k8s/dev
           run: |
             SHA=${{ needs.build-and-push.outputs.sha }}
             USER=${{ secrets.DOCKERHUB_USERNAME }}
             sed -i "s|image: .*/supermarket-backend:.*|image: ${USER}/supermarket-backend:${SHA}|" \
               k8s/dev/backend-deployment.yaml k8s/dev/ingestion-cronjob.yaml
             sed -i "s|image: .*/supermarket-web:.*|image: ${USER}/supermarket-web:${SHA}|" \
               k8s/dev/web-deployment.yaml
         - name: Commit manifest bump
           run: |
             git config user.name "github-actions[bot]"
             git config user.email "github-actions[bot]@users.noreply.github.com"
             git add k8s/dev/*.yaml
             git commit -m "deploy: bump dev images to ${{ needs.build-and-push.outputs.sha }}" || echo "no changes to commit"
             git push
   ```
10. Add the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets in GitHub's
    repo settings (manual, one-time, outside version control).
11. Open a trivial PR (e.g. a comment change), confirm `ci.yml` runs and passes, merge it,
    and confirm `build-and-deploy-dev.yml` runs, pushes new images, and commits a manifest
    bump to `main` — then confirm that bump commit does **not** itself trigger another CI/CD
    run (verifying the `GITHUB_TOKEN` loop-prevention behavior).
12. Confirm ArgoCD (CP11) picks up the bumped `k8s/dev/` manifests within its sync interval
    and the dev deployment updates to the new image.
13. Commit all workflow/migration files.

## Testing Tasks

- [ ] `ci.yml` passes on a PR: lint, full test suite, and the Postgres migration/compatibility
      check.
- [ ] `build-and-deploy-dev.yml` builds, pushes, and bumps `k8s/dev/` on merge to `main`.
- [ ] Confirmed manifest-bump commit does not retrigger the workflow (no loop).
- [ ] ArgoCD dev `Application` reflects the new image tag after the bump.

## Acceptance Criteria

A PR cannot merge unless lint, the full test suite, and the Postgres compatibility check all
pass; a merge to `main` results in new images being built, pushed, and automatically deployed
to the dev namespace via ArgoCD, without any manual step beyond the merge itself.

## Risks

- Alembic's autogenerated migration (step 4) may not perfectly capture every constraint from
  the hand-written CP2 models — review it manually rather than trusting autogenerate blindly.
- `DOCKERHUB_TOKEN`/`DOCKERHUB_USERNAME` must be kept as GitHub secrets, never committed —
  confirm `.gitignore`/repo scan has no accidental leakage before the first push.

## Notes

CP13 introduces the `k8s/prod/` promotion flow, which reuses this same CI-built image tags —
it does not add a separate build step.

## Definition of Done

- [ ] Alembic wired in; initial migration matches CP2's schema.
- [ ] `ci.yml` and `build-and-deploy-dev.yml` implemented and verified end-to-end on a real
      PR/merge.
- [ ] Committed with message referencing CP12.
