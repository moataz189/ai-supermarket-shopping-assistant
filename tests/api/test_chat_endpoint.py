from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.api.dependencies import get_agent_app
from app.api.main import app
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient

client = TestClient(app)


def _build_fake_app(items, candidates, prices, budget=None):
    llm = FakeLLM(ParsedRequestSchema(items=items, budget=budget))
    fake_client = FakeSupermarketDataClient(candidates, prices)
    return build_graph(fake_client, llm, MemorySaver())


def test_grocery_list_returns_both_carts_and_awaits_choice():
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
    fake_app = _build_fake_app(["milk"], candidates, prices)
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "milk"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "awaiting_retailer_choice"
        thread_id = body["thread_id"]
        assert thread_id
        carts = body["clarification"]["carts"]
        assert set(carts.keys()) == {"shufersal", "rami_levy"}
        assert carts["shufersal"]["total"] == 6.0
        assert carts["rami_levy"]["total"] == 5.5

        resume = client.post("/chat", json={"thread_id": thread_id, "message": "shufersal"})
        assert resume.status_code == 200
        resume_body = resume.json()
        assert resume_body["thread_id"] == thread_id
        assert resume_body["status"] == "success"
        assert resume_body["chosen_retailer"] == "shufersal"
        assert resume_body["carts"]["shufersal"]["total"] == 6.0
        assert resume_body["carts"]["rami_levy"]["total"] == 5.5
    finally:
        app.dependency_overrides.clear()


def test_ambiguous_item_then_resumes():
    candidates = {
        ("butter", "shufersal"): [
            {"item_code": "S-TNUVA", "name": "Tnuva", "price": 5.0},
            {"item_code": "S-TARA", "name": "Tara", "price": 5.5},
        ],
        ("butter", "rami_levy"): [
            {"item_code": "R-TNUVA", "name": "Tnuva", "price": 4.8},
            {"item_code": "R-PRES", "name": "President", "price": 6.0},
        ],
        ("Tnuva", "shufersal"): [{"item_code": "S-TNUVA", "name": "Tnuva", "price": 5.0}],
        ("Tnuva", "rami_levy"): [{"item_code": "R-TNUVA", "name": "Tnuva", "price": 4.8}],
    }
    prices = {
        ("shufersal", "S-TNUVA"): {"unit_price": 5.0, "price": 5.0},
        ("rami_levy", "R-TNUVA"): {"unit_price": 4.8, "price": 4.8},
    }
    fake_app = _build_fake_app(["butter"], candidates, prices)
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "butter"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "needs_clarification"
        thread_id = body["thread_id"]
        assert body["clarification"]["reason"] == "ambiguous_product"
        option_ids = {opt["id"] for opt in body["clarification"]["options"]}
        assert option_ids == {"Tnuva", "Tara", "President"}
        assert body["clarification"]["availability_by_retailer"] == {
            "shufersal": ["Tara", "Tnuva"],
            "rami_levy": ["President", "Tnuva"],
        }

        resume = client.post("/chat", json={"thread_id": thread_id, "message": "Tnuva"})
        assert resume.status_code == 200
        resume_body = resume.json()
        assert resume_body["thread_id"] == thread_id
        assert resume_body["status"] == "awaiting_retailer_choice"
        carts = resume_body["clarification"]["carts"]
        assert carts["shufersal"]["items"][0]["item_code"] == "S-TNUVA"
        assert carts["rami_levy"]["items"][0]["item_code"] == "R-TNUVA"
    finally:
        app.dependency_overrides.clear()
