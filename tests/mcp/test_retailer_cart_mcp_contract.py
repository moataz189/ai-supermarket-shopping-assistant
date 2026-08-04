import json

from mcp_servers.retailer_cart_mcp import server
from tests.mcp.mock_retailer_adapter import MockRetailerAdapter


def _never_construct():
    def _factory():
        raise AssertionError("adapter should never be constructed when the check fails fast")

    return _factory


async def test_prepare_retailer_cart_refuses_without_session(tmp_path):
    mcp_server = server.create_server(
        adapters={"mock_retailer": _never_construct()}, sessions_dir=str(tmp_path)
    )

    _, structured = await mcp_server.call_tool(
        "prepare_retailer_cart",
        {
            "retailer": "mock_retailer",
            "items": [
                {"name": "Milk 3%", "item_code": "SKU-MILK", "quantity": 1},
                {"name": "Bread", "item_code": "SKU-BREAD", "quantity": 2},
            ],
        },
    )

    assert structured["blocked"] is True
    assert structured["blocked_reason"] == "login_required"
    assert structured["added"] == []
    assert len(structured["failed"]) == 2
    for item in structured["failed"]:
        assert item["status"] == "error"
        assert item["reason"] == "no_login_session"


async def test_prepare_retailer_cart_refuses_for_unsupported_retailer():
    mcp_server = server.create_server(adapters={}, sessions_dir="sessions")

    _, structured = await mcp_server.call_tool(
        "prepare_retailer_cart",
        {"retailer": "not_a_real_retailer", "items": [{"name": "Milk", "item_code": "X", "quantity": 1}]},
    )

    assert structured["blocked"] is True
    assert structured["blocked_reason"] == "unsupported_retailer"
    assert structured["added"] == []
    assert structured["failed"] == [
        {
            "name": "Milk",
            "item_code": "X",
            "status": "error",
            "reason": "unsupported_retailer",
            "matched_by": None,
            "quantity_confirmed": None,
        }
    ]


async def test_prepare_retailer_cart_succeeds_with_session_present(mock_site, tmp_path):
    session_file = tmp_path / "mock_retailer.json"
    session_file.write_text(json.dumps({"cookies": [], "origins": []}))

    mcp_server = server.create_server(
        adapters={"mock_retailer": lambda: MockRetailerAdapter(mock_site)}, sessions_dir=str(tmp_path)
    )

    _, structured = await mcp_server.call_tool(
        "prepare_retailer_cart",
        {"retailer": "mock_retailer", "items": [{"name": "Bread", "item_code": "SKU-BREAD", "quantity": 1}]},
    )

    assert structured["blocked"] is False
    assert structured["blocked_reason"] is None
    assert len(structured["added"]) == 1
    added = structured["added"][0]
    assert added["item_code"] == "SKU-BREAD"
    assert added["status"] == "added"
    assert added["matched_by"] == "item_code"
    assert added["quantity_confirmed"] == 1
    assert structured["cart_url"] == f"{mock_site}/cart"
