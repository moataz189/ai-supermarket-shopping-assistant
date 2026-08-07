from langgraph.types import interrupt


async def choose_retailer(state):
    carts = state["retailer_carts"]
    shufersal, rami_levy = carts["shufersal"], carts["rami_levy"]
    # A ₪0.00 cart (every requested item missing) is not "cheaper" than a real, priced
    # one — comparing them by raw total diff would make an empty cart look like the best
    # deal. Savings only mean something when both sides are real, priced carts.
    comparable = shufersal["total"] > 0 and rami_levy["total"] > 0
    diff = round(shufersal["total"] - rami_levy["total"], 2) if comparable else 0

    answer = interrupt({
        "reason": "retailer_choice",
        "question": "Here are both carts — which would you like to use?",
        "carts": {
            "shufersal": {**shufersal, "savings_vs_other": max(-diff, 0)},
            "rami_levy": {**rami_levy, "savings_vs_other": max(diff, 0)},
        },
        "options": [
            {"id": "shufersal", "label": "Use Shufersal Online"},
            {"id": "rami_levy", "label": "Use Rami Levy Online"},
            {"id": "decline", "label": "Neither — just show me this"},
        ],
    })
    return {"chosen_retailer": answer if answer in ("shufersal", "rami_levy") else None}
