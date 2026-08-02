# AI Supermarket Shopping Assistant

An agent that turns a natural-language shopping request (grocery list or recipe) into two
independently-optimized shopping carts, one per retailer, and prepares the chosen retailer's
real cart via browser automation — stopping before checkout, login, or payment.

See [`docs/spec.md`](docs/spec.md) for the full design and [`docs/plan.md`](docs/plan.md) for
the implementation plan.

## Development

```bash
make install   # install runtime + dev dependencies
make lint      # run ruff
make test      # run pytest
make coverage  # run pytest with terminal + XML coverage reports
make run       # run the FastAPI app locally
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request into `main` (and as a
safety check on pushes to `main`):

- Ruff checks code quality (`make lint`).
- Pytest runs the full test suite (`make coverage`, i.e. `make test` plus coverage
  collection).
- `pytest-cov` generates `coverage.xml` alongside a terminal report.
- Codecov uploads and displays the coverage report for the run.

This is an early, basic CI workflow — see `docs/plan/12-github-actions-cicd.md` for the later
checkpoint that extends it with container builds, image publishing, manifest updates, and
deployment.
