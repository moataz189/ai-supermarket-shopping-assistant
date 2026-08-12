from unittest.mock import AsyncMock, patch

import pytest
from prometheus_client import generate_latest

from app.agent.mcp_clients import McpRecipeClient, McpRetailerCartClient, McpSupermarketDataClient


class _FakeAsyncContextManager:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc_info):
        return False


def _patch_successful_call(monkeypatch_target, structured_content):
    session = AsyncMock()
    session.initialize = AsyncMock()
    tool_result = AsyncMock()
    tool_result.structuredContent = structured_content
    session.call_tool = AsyncMock(return_value=tool_result)

    stream_ctx = _FakeAsyncContextManager((None, None, None))
    session_ctx = _FakeAsyncContextManager(session)

    return (
        patch(f"{monkeypatch_target}.streamablehttp_client", return_value=stream_ctx),
        patch(f"{monkeypatch_target}.ClientSession", return_value=session_ctx),
    )


async def test_supermarket_client_call_increments_success_counter():
    p1, p2 = _patch_successful_call("app.agent.mcp_clients", {"candidates": []})
    with p1, p2:
        client = McpSupermarketDataClient("http://supermarket-mcp:8001/mcp")
        before = generate_latest().decode()
        await client.search_product("milk", "shufersal")
        after = generate_latest().decode()

    assert 'mcp_call_total{mcp_service="supermarket",status="success"}' in after
    assert before != after


async def test_recipe_client_call_increments_success_counter():
    p1, p2 = _patch_successful_call("app.agent.mcp_clients", {"recipes": []})
    with p1, p2:
        client = McpRecipeClient("http://recipe-mcp:8002/mcp")
        await client.search_recipes("shakshuka")

    after = generate_latest().decode()
    assert 'mcp_call_total{mcp_service="recipe",status="success"}' in after


async def test_retailer_cart_client_call_records_error_counter_on_exception():
    with patch(
        "app.agent.mcp_clients.streamablehttp_client",
        side_effect=ConnectionError("mcp unreachable"),
    ):
        client = McpRetailerCartClient("http://retailer-cart-mcp:8003/mcp")
        with pytest.raises(ConnectionError):
            await client.prepare_retailer_cart("shufersal", [])

    after = generate_latest().decode()
    assert 'mcp_call_total{mcp_service="retailer_cart",status="error"}' in after


async def test_retailer_cart_client_sends_api_key_header_and_environment_argument():
    captured = {}

    def _capturing_streamablehttp_client(url, headers=None, **kwargs):
        captured["headers"] = headers
        return _FakeAsyncContextManager((None, None, None))

    session = AsyncMock()
    session.initialize = AsyncMock()
    tool_result = AsyncMock()
    tool_result.structuredContent = {
        "retailer": "shufersal", "added": [], "failed": [], "blocked": False,
        "blocked_reason": None, "cart_url": None,
    }
    session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch("app.agent.mcp_clients.streamablehttp_client", side_effect=_capturing_streamablehttp_client),
        patch("app.agent.mcp_clients.ClientSession", return_value=_FakeAsyncContextManager(session)),
    ):
        client = McpRetailerCartClient(
            "https://retailer-cart.fursa.click/mcp", api_key="secret123", environment="dev"
        )
        await client.prepare_retailer_cart("shufersal", [])

    assert captured["headers"] == {"X-API-Key": "secret123"}
    session.call_tool.assert_awaited_once_with(
        "prepare_retailer_cart", {"retailer": "shufersal", "items": [], "environment": "dev"}
    )
