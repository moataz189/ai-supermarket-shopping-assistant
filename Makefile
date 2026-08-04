.PHONY: install lint test coverage run

# Playwright drives a real (headless) Chromium for the Retailer-Cart MCP tests (tests/mcp)
# against the mock retailer site — the pip package alone doesn't ship the browser binary,
# so pytest fails with "Executable doesn't exist" without the `playwright install` below.
# --with-deps additionally installs Chromium's OS-level dependencies on Linux (CI); it's a
# safe no-op on macOS. Chromium only — this project never launches another browser engine.
install:
	pip install -r requirements.txt -r requirements-dev.txt
	playwright install --with-deps chromium

lint:
	ruff check app tests mcp_servers

test:
	pytest

coverage:
	pytest --cov=app --cov=mcp_servers --cov-report=term-missing --cov-report=xml

run:
	python -m uvicorn app.api.main:app --reload
