from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from prometheus_client import generate_latest

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.api.dependencies import get_agent_app
from app.api.main import app
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient

client = TestClient(app)


def test_metrics_endpoint_exposes_prometheus_text_format():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_chat_request_increments_request_and_request_type_counters():
    llm = FakeLLM(ParsedRequestSchema(request_type="general_chat", reply="Hi there!"))
    fake_app = build_graph(FakeSupermarketDataClient({}, {}), llm, MemorySaver())
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        before = generate_latest().decode()
        response = client.post("/chat", json={"message": "hi"})
        assert response.status_code == 200
        after = generate_latest().decode()
    finally:
        app.dependency_overrides.clear()

    assert 'agent_chat_requests_total{status="success"}' in after
    assert 'agent_request_type_total{request_type="general_chat"}' in after
    assert before != after


def test_retailer_choice_and_cart_preparation_counters_increment():
    # FakeSupermarketDataClient/FakeRetailerCartClient are protocol-conforming
    # in-memory stand-ins used throughout the agent test suite — they never go through
    # McpSupermarketDataClient/McpRetailerCartClient._call, so mcp_call_total isn't
    # observable here; see tests/agent/test_mcp_clients_metrics.py for that.
    from tests.agent.fakes import FakeRetailerCartClient

    candidates = {
        ("milk", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("Milk 3%", "shufersal"): [{"item_code": "S-MILK", "name": "Milk 3%", "price": 6.0}],
        ("milk", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
        ("Milk 3%", "rami_levy"): [{"item_code": "R-MILK", "name": "Milk 3%", "price": 5.5}],
    }
    prices = {
        ("shufersal", "S-MILK"): {"unit_price": 6.0, "price": 6.0},
        ("rami_levy", "R-MILK"): {"unit_price": 5.5, "price": 5.5},
    }
    canned_result = {
        "retailer": "shufersal",
        "added": [{
            "name": "milk", "item_code": "S-MILK", "status": "added", "reason": None,
            "matched_by": "item_code", "quantity_confirmed": 1,
        }],
        "failed": [],
        "blocked": False,
        "blocked_reason": None,
        "cart_url": "https://www.shufersal.co.il/online/he/cart",
    }
    llm = FakeLLM(ParsedRequestSchema(items=["milk"]))
    fake_app = build_graph(
        FakeSupermarketDataClient(candidates, prices), llm, MemorySaver(),
        retailer_cart_client=FakeRetailerCartClient(canned_result),
    )
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "milk"})
        thread_id = response.json()["thread_id"]
        resume = client.post("/chat", json={"thread_id": thread_id, "message": "shufersal"})
        assert resume.status_code == 200
        after = generate_latest().decode()
    finally:
        app.dependency_overrides.clear()

    assert 'retailer_choice_total{retailer="shufersal"}' in after
    assert 'cart_preparation_total{status="success"}' in after
