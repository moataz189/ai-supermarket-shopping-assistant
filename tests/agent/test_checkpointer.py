from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.checkpointer import get_checkpointer


def test_defaults_to_memory_saver(monkeypatch):
    monkeypatch.delenv("CHECKPOINTER_BACKEND", raising=False)
    assert isinstance(get_checkpointer(), MemorySaver)


def test_memory_backend_explicit(monkeypatch):
    monkeypatch.setenv("CHECKPOINTER_BACKEND", "memory")
    assert isinstance(get_checkpointer(), MemorySaver)


def test_sqlite_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("CHECKPOINTER_BACKEND", "sqlite")
    monkeypatch.setenv("CHECKPOINTER_SQLITE_PATH", str(tmp_path / "checkpoints.db"))
    from langgraph.checkpoint.sqlite import SqliteSaver

    with get_checkpointer() as saver:
        assert isinstance(saver, SqliteSaver)


def test_dynamodb_backend_requires_table_name(monkeypatch):
    monkeypatch.setenv("CHECKPOINTER_BACKEND", "dynamodb")
    monkeypatch.delenv("CHECKPOINT_DYNAMODB_TABLE", raising=False)
    with pytest.raises(RuntimeError, match="CHECKPOINT_DYNAMODB_TABLE"):
        get_checkpointer()


def test_dynamodb_backend_constructs_saver_with_table_and_region(monkeypatch):
    monkeypatch.setenv("CHECKPOINTER_BACKEND", "dynamodb")
    monkeypatch.setenv("CHECKPOINT_DYNAMODB_TABLE", "supermarket-assistant-checkpoints")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    with patch("langgraph_checkpoint_aws.DynamoDBSaver") as mock_saver:
        get_checkpointer()

    mock_saver.assert_called_once_with(
        table_name="supermarket-assistant-checkpoints", region_name="us-east-1"
    )


def test_unsupported_backend_raises():
    with (
        patch.dict("os.environ", {"CHECKPOINTER_BACKEND": "bogus"}),
        pytest.raises(ValueError, match="Unsupported CHECKPOINTER_BACKEND"),
    ):
        get_checkpointer()
