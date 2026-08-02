from langgraph.types import interrupt


async def choose_retailer(state):
    carts = state["retailer_carts"]
    shufersal, rami_levy = carts["shufersal"], carts["rami_levy"]
    diff = round(shufersal["total"] - rami_levy["total"], 2)

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
