# CP1 — Project Scaffolding & Local Dev Environment

Spec milestone: M1. Depends on: nothing (first checkpoint).

## Goal

Stand up the repository skeleton, Python tooling, linting, and test runner, plus a trivial
FastAPI health endpoint — so every later checkpoint has a working, testable foundation.

## Scope

Directory skeleton, dependency management, lint/test configuration, `.env` handling, one
smoke-test endpoint. No business logic, no database, no agent, no MCP servers yet.

## Deliverables

- `make install && make test` succeeds on a clean clone.
- `make run` serves `GET /health` → `200 {"status": "ok"}`.
- `make lint` runs clean.

## Files to Create

```
pyproject.toml
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
2. Write `pyproject.toml`:
   ```toml
   [project]
   name = "supermarket-assistant"
   version = "0.1.0"
   requires-python = ">=3.11"
   dependencies = [
     "fastapi>=0.111",
     "uvicorn[standard]>=0.29",
     "sqlalchemy>=2.0",
     "pydantic>=2.7",
   ]

   [project.optional-dependencies]
   dev = [
     "pytest>=8.0",
     "pytest-asyncio>=0.23",
     "httpx>=0.27",
     "ruff>=0.4",
   ]

   [tool.ruff]
   line-length = 100

   [tool.pytest.ini_options]
   testpaths = ["tests"]
   ```
3. Write `app/api/main.py`:
   ```python
   from fastapi import FastAPI

   app = FastAPI(title="AI Supermarket Shopping Assistant")


   @app.get("/health")
   def health() -> dict[str, str]:
       return {"status": "ok"}
   ```
4. Write the failing test first, `tests/api/test_health.py`:
   ```python
   from fastapi.testclient import TestClient

   from app.api.main import app

   client = TestClient(app)


   def test_health_returns_ok():
       response = client.get("/health")
       assert response.status_code == 200
       assert response.json() == {"status": "ok"}
   ```
5. Create a virtualenv and install: `python -m venv .venv && . .venv/bin/activate && pip
   install -e ".[dev]"`.
6. Run `pytest -v` — verify `test_health_returns_ok` passes.
7. Run `ruff check app tests` — fix any reported issues.
8. Write `Makefile`:
   ```makefile
   .PHONY: install lint test run

   install:
   	pip install -e ".[dev]"

   lint:
   	ruff check app tests mcp_servers

   test:
   	pytest

   run:
   	uvicorn app.api.main:app --reload
   ```
9. Write `.env.example`:
   ```
   DATABASE_URL=sqlite:///./app.db
   BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
   AWS_REGION=us-east-1
   SPOONACULAR_API_KEY=changeme
   ```
10. Write `.gitignore` (Python, `.venv/`, `__pycache__/`, `*.db`, `.env`, `node_modules/`,
    `.terraform/`, `*.tfstate*`).
11. Write a short `README.md`: project one-liner, link to `docs/spec.md` and `docs/plan.md`,
    and the four `make` commands from step 8.
12. Run `make run` in one terminal, `curl localhost:8000/health` in another — verify
    `{"status":"ok"}`.

## Testing Tasks

- [ ] `pytest tests/api/test_health.py -v` passes.
- [ ] `ruff check app tests` reports zero issues.
- [ ] Manual: `make run` + `curl localhost:8000/health` returns 200.

## Acceptance Criteria

A fresh clone of the repo, with only a Python 3.11+ interpreter available, can run
`make install && make test` and see one passing test, then `make run` and reach `/health`.

## Risks

- Python version drift between a contributor's machine and the container image built in
  CP8 — mitigated by pinning `requires-python` here and reusing the same base image tag in
  CP8's Dockerfile.

## Notes

`mcp_servers/` and `web/` are placeholders here — populated in CP3/CP6 and CP5/CP15
respectively. Do not add business logic in this checkpoint.

## Definition of Done

- [ ] Directory skeleton, `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore`, `README.md`
      exist.
- [ ] `test_health_returns_ok` passes.
- [ ] `ruff check` is clean.
- [ ] Changes committed with message referencing CP1.
