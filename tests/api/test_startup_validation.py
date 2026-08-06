import pytest
from fastapi.testclient import TestClient

from app.api.main import app


def test_startup_fails_clearly_when_bedrock_model_id_missing(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

    with pytest.raises(RuntimeError, match="BEDROCK_MODEL_ID"), TestClient(app):
        pass


def test_startup_succeeds_when_bedrock_model_id_set(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
