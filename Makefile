.PHONY: install lint test coverage run

install:
	pip install -r requirements.txt -r requirements-dev.txt

lint:
	ruff check app tests mcp_servers

test:
	pytest

coverage:
	pytest --cov=app --cov=mcp_servers --cov-report=term-missing --cov-report=xml

run:
	python -m uvicorn app.api.main:app --reload
