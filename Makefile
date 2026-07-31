.PHONY: install lint test run

install:
	pip install -r requirements.txt -r requirements-dev.txt

lint:
	ruff check app tests mcp_servers

test:
	pytest

run:
	python -m uvicorn app.api.main:app --reload
