from langgraph.types import interrupt

from app.agent.nodes.resolve_items import _unique_labels

MAX_CANDIDATES_SHOWN = 5


async def resolve_ambiguity(state):
    item_name = state["pending_clarification_item"]
    by_retailer = state["item_candidates"][item_name]
    unique = _unique_labels(by_retailer)[:MAX_CANDIDATES_SHOWN]

    answer = interrupt({
        "reason": "ambiguous_product",
        "question": f"I found a few options for '{item_name}' — which one did you mean?",
        "options": [{"id": c["name"], "label": c["name"]} for c in unique],
        "availability_by_retailer": {
            retailer: sorted({c["name"] for c in candidates})
            for retailer, candidates in by_retailer.items()
        },
    })
    resolved = {**state.get("resolved_choices", {}), item_name: answer}
    return {"resolved_choices": resolved, "pending_clarification_item": None}


def route_after_resolve(state) -> str:
    return "resolve_ambiguity" if state.get("pending_clarification_item") else "build_shufersal_cart"
