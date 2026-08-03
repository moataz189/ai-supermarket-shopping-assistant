from langgraph.types import interrupt

from app.agent.state import AgentState


async def resolve_recipe_ambiguity(state: AgentState) -> AgentState:
    candidates = state["recipe_candidates"]
    answer = interrupt({
        "reason": "ambiguous_recipe",
        "question": "I found a few recipes — which one did you mean?",
        "options": [{"id": str(c["id"]), "label": c["display_title"]} for c in candidates],
    })
    chosen = next(c for c in candidates if str(c["id"]) == answer)
    return {
        "chosen_recipe_id": chosen["id"],
        "chosen_recipe": {**chosen, "servings": None},
        "recipe_ambiguous": False,
    }
