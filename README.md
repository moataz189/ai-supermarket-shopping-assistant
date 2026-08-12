# AI Supermarket Shopping Assistant

An agent that turns a natural-language shopping request (grocery list or recipe) into two
independently-optimized shopping carts, one per retailer, and prepares the chosen retailer's
real cart via browser automation — stopping before checkout, login, or payment.

See [`docs/spec.md`](docs/spec.md) for the full design and [`docs/plan.md`](docs/plan.md) for
the implementation plan.

## Development

```bash
make install   # install runtime + dev dependencies, plus Playwright's Chromium browser
make lint      # run ruff
make test      # run pytest
make coverage  # run pytest with terminal + XML coverage reports
make run       # run the FastAPI app locally
```

`make install` is enough on a freshly cloned checkout — no separate `playwright install` step
needed. It installs the Python packages and then runs `playwright install --with-deps
chromium` (Chromium only; that's the only browser engine this project launches), which
downloads the browser binary itself and, on Linux, its OS-level dependencies. Without this
step, the Retailer-Cart MCP tests (`tests/mcp/test_retailer_cart_automation.py` and
`tests/mcp/test_retailer_cart_mcp_contract.py`) fail with `BrowserType.launch: Executable
doesn't exist` — those tests drive a real headless Chromium against a local mock retailer
site (`tests/mcp/mock_site_server.py`), never a real retailer's website.

## Running with Docker

No local Python/Node toolchain needed — only Docker. This runs the **real** backend, all
three MCP servers, and the real Shufersal/Rami Levy adapters (the mock retailer site is
test-only, never part of this stack).

```bash
cp .env.example .env         # fill in BEDROCK_MODEL_ID, AWS_REGION, SPOONACULAR_API_KEY
mkdir -p sessions             # must exist (even empty) before `docker compose up`

docker compose --profile tools run --rm ingestion   # one-time: load fixture products into SQLite
docker compose up --build                           # first run: builds all 6 images
```

Open **http://localhost:3000**. Other useful commands:

```bash
docker compose up -d          # subsequent runs, detached (no rebuild needed unless code changed)
docker compose logs -f backend           # tail one service's logs
docker compose down                      # stop and remove containers (keeps the DB volume)
./scripts/smoke_test.sh                  # build + start + healthcheck + teardown, one shot
```

A valid `BEDROCK_MODEL_ID` (+ working AWS credentials via the local-only `~/.aws` mount) is
required for the agent to respond at all — the backend fails fast at startup if it's unset.
A valid `SPOONACULAR_API_KEY` is required for the recipe flow. A previously-captured session
under `./sessions/<environment>/<retailer>.json` (CP8's `login.py`, run locally, never in a
container; `<environment>` defaults to `prod`) is required for a real (non-`login_required`)
retailer-cart attempt.

Ports: web `3000`, backend `8000`, supermarket-mcp `8001`, recipe-mcp `8002`,
retailer-cart-mcp `8003`. See [`docs/plan/09-containerization.md`](docs/plan/09-containerization.md)
for the full architecture and design decisions.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request into `main` (and as a
safety check on pushes to `main`):

- `make install` sets up dependencies, Chromium included — the same target used locally, so
  there's no separate browser-install step to keep in sync.
- Ruff checks code quality (`make lint`).
- Pytest runs the full test suite (`make coverage`, i.e. `make test` plus coverage
  collection), including the Playwright-driven Retailer-Cart MCP tests — those only ever
  target the local mock retailer site (`tests/mcp/mock_site_server.py`), never a real
  retailer's website.
- `pytest-cov` generates `coverage.xml` alongside a terminal report.
- Codecov uploads and displays the coverage report for the run.

This is an early, basic CI workflow — see `docs/plan/12-github-actions-cicd.md` for the later
checkpoint that extends it with container builds, image publishing, manifest updates, and
deployment.
