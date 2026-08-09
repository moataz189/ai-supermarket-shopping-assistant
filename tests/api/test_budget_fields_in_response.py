from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.api.dependencies import get_agent_app
from app.api.main import app
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient

client = TestClient(app)


def test_chat_response_includes_allowed_max_and_no_items_fit_budget():
    llm = FakeLLM(ParsedRequestSchema(items=["milk"], budget=20))
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
    fake_app = build_graph(FakeSupermarketDataClient(candidates, prices), llm, MemorySaver())
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "milk under 20"})
        assert response.status_code == 200
        thread_id = response.json()["thread_id"]

        # Resume with a retailer choice to reach the final ChatResponse.carts field
        # (typed dict[str, RetailerCart]) -- the interrupt payload's own `carts` field
        # is an untyped dict and would pass this assertion even without the schema
        # change, since pydantic never validates it.
        resume = client.post("/chat", json={"thread_id": thread_id, "message": "shufersal"})
        assert resume.status_code == 200
        cart = resume.json()["carts"]["shufersal"]
        assert cart["allowed_max"] == 22.0
        assert cart["no_items_fit_budget"] is False
    finally:
        app.dependency_overrides.clear()
