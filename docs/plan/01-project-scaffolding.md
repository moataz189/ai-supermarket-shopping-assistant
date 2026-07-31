# CP1 — Project Scaffolding & Local Dev Environment

Spec milestone: M1. Depends on: nothing (first checkpoint).

## Goal

Stand up the repository skeleton, Python tooling, linting, and test runner, plus a trivial
FastAPI health endpoint — so every later checkpoint has a working, testable foundation.

## Scope

Directory skeleton, dependency management (`requirements.txt`/`requirements-dev.txt`),
lint/test configuration, `.env` handling, one smoke-test endpoint. No business logic, no
database, no agent, no MCP servers yet.

**Dependency management note**: this project uses plain `requirements.txt` (runtime) /
`requirements-dev.txt` (dev/test only) files, not `pyproject.toml` package metadata or
`pip install -e .`. `pyproject.toml` still exists, but only for tool configuration
(`ruff`, `pytest`) — never for dependency declarations. Every later checkpoint that adds a
package appends it to one of these two files (runtime vs. dev/test — the file lists each
checkpoint's addition explicitly), and production Docker images (CP9) install only
`requirements.txt`, keeping them free of test/dev tooling.

## Deliverables

- `make install && make test` succeeds on a clean clone.
- `make run` serves `GET /health` → `200 {"status": "ok"}`.
- `make lint` runs clean.

## Files to Create

```
pyproject.toml
requirements.txt
requirements-dev.txt
Makefile
.gitignore
.env.example
README.md
app/__init__.py
app/api/__init__.py
app/api/main.py
tests/__init__.py
tests/api/__init__.py
tests/api/test_health.py
mcp_servers/.gitkeep
web/.gitkeep
infra/.gitkeep
k8s/.gitkeep
```

## Detailed Implementation Steps

1. Create the directory skeleton:
   ```bash
   mkdir -p app/api tests/api mcp_servers web infra k8s
   touch mcp_servers/.gitkeep web/.gitkeep infra/.gitkeep k8s/.gitkeep
   ```
2. Write `requirements.txt` (runtime dependencies only):
   ```
   fastapi>=0.111
   uvicorn[standard]>=0.29
   sqlalchemy>=2.0
   pydantic>=2.7
   ```
3. Write `requirements-dev.txt` (test/dev tooling only, never installed in production
   images):
   ```
   -r requirements.txt
   pytest>=8.0
   pytest-asyncio>=0.23
   httpx>=0.27
   ruff>=0.4
   ```
   (`-r requirements.txt` at the top means `pip install -r requirements-dev.txt` alone
   already pulls in runtime deps too — convenient for local dev, where `make install`
   installs both anyway.)
4. Write `pyproject.toml` — **tool configuration only**, no `[project]`/dependency
   sections:
   ```toml
   [tool.ruff]
   line-length = 100

   [tool.pytest.ini_options]
   testpaths = ["tests"]
   ```
5. Write `app/api/main.py`:
   ```python
   from fastapi import FastAPI

   app = FastAPI(title="AI Supermarket Shopping Assistant")


   @app.get("/health")
   def health() -> dict[str, str]:
       return {"status": "ok"}
   ```
6. Write the failing test first, `tests/api/test_health.py`:
   ```python
   from fastapi.testclient import TestClient

   from app.api.main import app

   client = TestClient(app)


   def test_health_returns_ok():
       response = client.get("/health")
       assert response.status_code == 200
       assert response.json() == {"status": "ok"}
   ```
7. Create a virtualenv and install: `python -m venv .venv && . .venv/bin/activate && pip
   install -r requirements.txt -r requirements-dev.txt`.
8. Run `pytest -v` — verify `test_health_returns_ok` passes. (Since `app/__init__.py` and
   `tests/__init__.py` both exist, pytest's default import mode inserts the repo root — the
   first ancestor directory *without* an `__init__.py` — onto `sys.path`, so `app` imports
   correctly with no package installation needed.)
9. Run `ruff check app tests` — fix any reported issues.
10. Write `Makefile`:
    ```makefile
    .PHONY: install lint test run

    install:
    	pip install -r requirements.txt -r requirements-dev.txt

    lint:
    	ruff check app tests mcp_servers

    test:
    	pytest

    run:
    	python -m uvicorn app.api.main:app --reload
    ```
    (`python -m uvicorn ...`, not a bare `uvicorn ...` — using `-m` guarantees the current
    directory is on `sys.path`, so `app.api.main` resolves without installing the local
    package, matching the no-`pip install -e .` approach.)
11. Write `.env.example`:
    ```
    DATABASE_URL=sqlite:///./app.db
    BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
    AWS_REGION=us-east-1
    SPOONACULAR_API_KEY=changeme
    ```
12. Write `.gitignore` (Python, `.venv/`, `__pycache__/`, `*.db`, `.env`, `node_modules/`,
    `.terraform/`, `*.tfstate*`).
13. Write a short `README.md`: project one-liner, link to `docs/spec.md` and `docs/plan.md`,
    and the four `make` commands from step 10.
14. Run `make run` in one terminal, `curl localhost:8000/health` in another — verify
    `{"status":"ok"}`.

## Testing Tasks

- [x] `pytest tests/api/test_health.py -v` passes.
- [x] `ruff check app tests` reports zero issues.
- [x] Manual: `make run` + `curl localhost:8000/health` returns 200.

## Acceptance Criteria

A fresh clone of the repo, with only a Python 3.11+ interpreter available, can run
`make install && make test` and see one passing test, then `make run` and reach `/health`.

## Risks

- Python version drift between a contributor's machine and the container images built in
  CP9 — mitigated by documenting the required Python version in `README.md` and reusing the
  same base image tag across CP9's Dockerfiles.
- Splitting deps across two files risks one being forgotten when a later checkpoint adds a
  package — mitigated by every checkpoint that introduces a new dependency stating exactly
  which file it goes in (runtime vs. dev-only), not just "add it as a dependency."

## Notes

`mcp_servers/` and `web/` are placeholders here — populated in CP3/CP6/CP8 and CP5/CP16
respectively. Do not add business logic in this checkpoint.

## Definition of Done

- [x] Directory skeleton, `pyproject.toml` (tool config only), `requirements.txt`,
      `requirements-dev.txt`, `Makefile`, `.env.example`, `.gitignore`, `README.md` exist.
- [x] `test_health_returns_ok` passes.
- [x] `ruff check` is clean.
- [x] Changes committed with message referencing CP1.
