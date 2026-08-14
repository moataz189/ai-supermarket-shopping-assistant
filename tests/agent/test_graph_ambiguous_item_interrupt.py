from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeSupermarketDataClient


async def test_ambiguous_item_interrupt_asks_independently_per_retailer_with_price():
    llm = FakeLLM(ParsedRequestSchema(items=["butter"]))
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
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "butter"}, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["reason"] == "ambiguous_product"
    options_by_retailer = payload["options_by_retailer"]
    assert {o["id"]: o["price"] for o in options_by_retailer["shufersal"]} == {"Tnuva": 5.0, "Tara": 5.5}
    assert {o["id"]: o["price"] for o in options_by_retailer["rami_levy"]} == {"Tnuva": 4.8, "President": 6.0}

    # One independent choice per retailer, not a single shared answer.
    final = await app.ainvoke(Command(resume={"shufersal": "Tnuva", "rami_levy": "Tnuva"}), config=config)

    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-TNUVA"
    assert carts["rami_levy"]["items"][0]["item_code"] == "R-TNUVA"


async def test_choosing_different_products_per_retailer_is_preserved_independently():
    llm = FakeLLM(ParsedRequestSchema(items=["butter"]))
    candidates = {
        ("butter", "shufersal"): [
            {"item_code": "S-TNUVA", "name": "Tnuva", "price": 5.0},
            {"item_code": "S-TARA", "name": "Tara", "price": 5.5},
        ],
        ("butter", "rami_levy"): [
            {"item_code": "R-TNUVA", "name": "Tnuva", "price": 4.8},
            {"item_code": "R-PRES", "name": "President", "price": 6.0},
        ],
        ("Tara", "shufersal"): [{"item_code": "S-TARA", "name": "Tara", "price": 5.5}],
        ("President", "rami_levy"): [{"item_code": "R-PRES", "name": "President", "price": 6.0}],
    }
    prices = {
        ("shufersal", "S-TARA"): {"unit_price": 5.5, "price": 5.5},
        ("rami_levy", "R-PRES"): {"unit_price": 6.0, "price": 6.0},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}

    await app.ainvoke({"raw_message": "butter"}, config=config)
    # Choosing Tara at Shufersal must not force/replace Rami Levy's own choice, and
    # vice versa — genuinely independent per-retailer selections.
    final = await app.ainvoke(Command(resume={"shufersal": "Tara", "rami_levy": "President"}), config=config)

    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-TARA"
    assert carts["rami_levy"]["items"][0]["item_code"] == "R-PRES"


async def test_free_text_resume_while_ambiguity_is_pending_re_asks_instead_of_crashing():
    # Real production crash (2026-08-14): the chat box's free-text input stays open the
    # whole time this card is showing (by design, for other clarification types), so
    # typing something instead of clicking an option sends a bare string as the resume
    # value -- must re-ask the same question, not crash on `**answer`.
    llm = FakeLLM(ParsedRequestSchema(items=["butter"]))
    candidates = {
        ("butter", "shufersal"): [
            {"item_code": "S-TNUVA", "name": "Tnuva", "price": 5.0},
            {"item_code": "S-TARA", "name": "Tara", "price": 5.5},
        ],
        ("butter", "rami_levy"): [{"item_code": "R-TNUVA", "name": "Tnuva", "price": 4.8}],
        ("Tnuva", "shufersal"): [{"item_code": "S-TNUVA", "name": "Tnuva", "price": 5.0}],
        ("Tnuva", "rami_levy"): [{"item_code": "R-TNUVA", "name": "Tnuva", "price": 4.8}],
    }
    prices = {
        ("shufersal", "S-TNUVA"): {"unit_price": 5.0, "price": 5.0},
        ("rami_levy", "R-TNUVA"): {"unit_price": 4.8, "price": 4.8},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t-free-text"}}

    first = await app.ainvoke({"raw_message": "butter"}, config=config)
    first_payload = first["__interrupt__"][0].value
    assert first_payload["reason"] == "ambiguous_product"

    reasked = await app.ainvoke(Command(resume="I typed something instead"), config=config)

    assert "__interrupt__" in reasked
    reasked_payload = reasked["__interrupt__"][0].value
    assert reasked_payload["reason"] == "ambiguous_product"
    assert reasked_payload["options_by_retailer"] == first_payload["options_by_retailer"]

    final = await app.ainvoke(Command(resume={"shufersal": "Tnuva"}), config=config)

    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-TNUVA"


async def test_retailer_with_a_single_candidate_auto_resolves_without_being_asked():
    # Shufersal has two real candidates (genuinely ambiguous); Rami Levy has exactly one
    # — it must never appear in options_by_retailer, and its own cart must already use
    # its auto-resolved product without the user ever choosing anything for it.
    llm = FakeLLM(ParsedRequestSchema(items=["pasta"]))
    candidates = {
        ("pasta", "shufersal"): [
            {"item_code": "S-PENNE", "name": "Penne", "price": 8.9},
            {"item_code": "S-FUSILLI", "name": "Fusilli", "price": 7.5},
        ],
        ("pasta", "rami_levy"): [
            {"item_code": "R-FUSILLI", "name": "Fusilli Rami Levy", "price": 7.9},
        ],
        ("Penne", "shufersal"): [{"item_code": "S-PENNE", "name": "Penne", "price": 8.9}],
        ("Fusilli Rami Levy", "rami_levy"): [{"item_code": "R-FUSILLI", "name": "Fusilli Rami Levy", "price": 7.9}],
    }
    prices = {
        ("shufersal", "S-PENNE"): {"unit_price": 8.9, "price": 8.9},
        ("rami_levy", "R-FUSILLI"): {"unit_price": 7.9, "price": 7.9},
    }
    client = FakeSupermarketDataClient(candidates, prices)
    app = build_graph(client, llm, MemorySaver())
    config = {"configurable": {"thread_id": "t3"}}

    result = await app.ainvoke({"raw_message": "pasta"}, config=config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert set(payload["options_by_retailer"]) == {"shufersal"}  # rami_levy never asked

    final = await app.ainvoke(Command(resume={"shufersal": "Penne"}), config=config)

    assert "__interrupt__" in final
    carts = final["__interrupt__"][0].value["carts"]
    assert carts["shufersal"]["items"][0]["item_code"] == "S-PENNE"
    assert carts["rami_levy"]["items"][0]["item_code"] == "R-FUSILLI"  # auto-resolved, never asked
