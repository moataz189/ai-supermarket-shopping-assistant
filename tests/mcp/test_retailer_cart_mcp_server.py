import json

import pytest
from starlette.testclient import TestClient

from mcp_servers.retailer_cart_mcp.server import create_server


def test_missing_api_key_is_rejected_when_key_configured():
    server = create_server(adapters={}, sessions_dir="sessions", api_key="secret123")
    client = TestClient(server.streamable_http_app())
    response = client.get("/health")
    assert response.status_code == 401


def test_correct_api_key_is_accepted():
    server = create_server(adapters={}, sessions_dir="sessions", api_key="secret123")
    client = TestClient(server.streamable_http_app())
    response = client.get("/health", headers={"X-API-Key": "secret123"})
    assert response.status_code == 200


def test_no_api_key_configured_is_a_no_op():
    # Matches today's docker-compose/local behavior — no key set, no enforcement.
    server = create_server(adapters={}, sessions_dir="sessions", api_key=None)
    client = TestClient(server.streamable_http_app())
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_prepare_retailer_cart_reads_environment_scoped_session(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    (sessions_dir / "dev").mkdir(parents=True)
    (sessions_dir / "dev" / "shufersal.json").write_text(json.dumps({"cookies": [], "origins": []}))

    calls = []

    class _FakeAdapter:
        retailer_name = "shufersal"

    async def _fake_prepare(adapter, items, storage_state_path):
        calls.append(storage_state_path)
        return {
            "retailer": "shufersal", "added": [], "failed": [], "blocked": False,
            "blocked_reason": None, "cart_url": None,
        }

    monkeypatch.setattr(
        "mcp_servers.retailer_cart_mcp.server.prepare_cart_for_retailer", _fake_prepare
    )
    server = create_server(
        adapters={"shufersal": _FakeAdapter}, sessions_dir=str(sessions_dir), api_key=None
    )
    # Call the underlying tool function directly rather than through the transport —
    # simplest way to assert on storage_state_path without a full MCP client round trip.
    tool = server._tool_manager.get_tool("prepare_retailer_cart")
    await tool.fn(retailer="shufersal", items=[], environment="dev")
    assert calls == [str(sessions_dir / "dev" / "shufersal.json")]


@pytest.mark.asyncio
async def test_prepare_retailer_cart_refuses_unsupported_environment(tmp_path, monkeypatch):
    class _FakeAdapter:
        retailer_name = "shufersal"

    server = create_server(
        adapters={"shufersal": _FakeAdapter}, sessions_dir=str(tmp_path), api_key=None
    )

    tool = server._tool_manager.get_tool("prepare_retailer_cart")
    result = await tool.fn(retailer="shufersal", items=[], environment="invalid_env")

    assert result.blocked is True
    assert result.blocked_reason == "unsupported_environment"


@pytest.mark.asyncio
async def test_prepare_retailer_cart_refuses_path_traversal_attempt(tmp_path, monkeypatch):
    # Ensure prepare_cart_for_retailer is never called (would indicate a path traversal escape)
    prepare_called = []

    async def _fake_prepare(adapter, items, storage_state_path):
        prepare_called.append(storage_state_path)
        return {
            "retailer": "shufersal", "added": [], "failed": [], "blocked": False,
            "blocked_reason": None, "cart_url": None,
        }

    monkeypatch.setattr(
        "mcp_servers.retailer_cart_mcp.server.prepare_cart_for_retailer", _fake_prepare
    )

    class _FakeAdapter:
        retailer_name = "shufersal"

    server = create_server(
        adapters={"shufersal": _FakeAdapter}, sessions_dir=str(tmp_path), api_key=None
    )

    tool = server._tool_manager.get_tool("prepare_retailer_cart")
    result = await tool.fn(retailer="shufersal", items=[], environment="../../tmp")

    # Should be refused at environment validation, not attempt path traversal
    assert result.blocked is True
    assert result.blocked_reason == "unsupported_environment"
    # prepare_cart_for_retailer should never be called
    assert prepare_called == []
