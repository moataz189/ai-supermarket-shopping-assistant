from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from app.api.dependencies import get_agent_app
from app.api.main import app
from tests.agent.fakes import FakeLLM, FakeRetailerCartClient, FakeSupermarketDataClient

client = TestClient(app)


def _build_fake_app(items, candidates, prices, budget=None, retailer_cart_client=None):
    llm = FakeLLM(ParsedRequestSchema(items=items, budget=budget))
    fake_client = FakeSupermarketDataClient(candidates, prices)
    return build_graph(fake_client, llm, MemorySaver(), retailer_cart_client=retailer_cart_client)


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


def test_choosing_retailer_invokes_playwright():
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
        "added": [
            {
                "name": "milk",
                "item_code": "S-MILK",
                "status": "added",
                "reason": None,
                "matched_by": "item_code",
                "quantity_confirmed": 1,
            }
        ],
        "failed": [],
        "blocked": False,
        "blocked_reason": None,
        "cart_url": "https://www.shufersal.co.il/online/he/cart",
    }
    retailer_cart_client = FakeRetailerCartClient(canned_result)
    fake_app = _build_fake_app(["milk"], candidates, prices, retailer_cart_client=retailer_cart_client)
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "milk"})
        thread_id = response.json()["thread_id"]

        resume = client.post("/chat", json={"thread_id": thread_id, "message": "shufersal"})
        assert resume.status_code == 200
        resume_body = resume.json()
        # The HTTP response goes through pydantic's RetailerCartItemResult, which fills
        # in the new requested_*/cart_* fields (None here — this is a plain grocery item,
        # not a recipe one) — canned_result itself has no such keys, so compare against
        # an explicitly-extended expectation rather than the raw fixture.
        expected_result = {
            **canned_result,
            "added": [
                {**canned_result["added"][0], "requested_quantity": None, "requested_unit": None,
                 "cart_quantity": None, "cart_unit": None}
            ],
        }
        assert resume_body["retailer_cart_result"] == expected_result
        assert len(retailer_cart_client.calls) == 1
    finally:
        app.dependency_overrides.clear()


def test_greeting_returns_a_conversational_message_not_a_shopping_flow():
    llm = FakeLLM(ParsedRequestSchema(request_type="general_chat", reply="Hi! How can I help?"))
    fake_app = build_graph(FakeSupermarketDataClient({}, {}), llm, MemorySaver())
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "hi"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["message"] == "Hi! How can I help?"
        assert body["carts"] == {}
        assert body["chosen_retailer"] is None
        assert body["clarification"] is None
    finally:
        app.dependency_overrides.clear()


def test_declining_skips_playwright():
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
    retailer_cart_client = FakeRetailerCartClient({"retailer": "shufersal"})
    fake_app = _build_fake_app(["milk"], candidates, prices, retailer_cart_client=retailer_cart_client)
    app.dependency_overrides[get_agent_app] = lambda: fake_app
    try:
        response = client.post("/chat", json={"message": "milk"})
        thread_id = response.json()["thread_id"]

        resume = client.post("/chat", json={"thread_id": thread_id, "message": "decline"})
        assert resume.status_code == 200
        resume_body = resume.json()
        assert resume_body["retailer_cart_result"] is None
        assert retailer_cart_client.calls == []
    finally:
        app.dependency_overrides.clear()
