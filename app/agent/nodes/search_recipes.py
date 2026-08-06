from app.agent.i18n import localize_title
from app.agent.state import AgentState


def make_search_recipes(recipe_client):
    async def search_recipes(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        query = parsed["recipe_query"]
        language = parsed.get("language", "en")

        raw_recipes = await recipe_client.search_recipes(query)
        candidates = [
            {
                "id": r["id"],
                "title": r["title"],
                "display_title": localize_title(r["title"], language),
            }
            for r in raw_recipes
        ]

        exact_matches = [
            c for c in candidates if c["title"].strip().lower() == query.strip().lower()
        ]
        ambiguous = len(candidates) > 1 and len(exact_matches) != 1

        result: AgentState = {"recipe_candidates": candidates, "recipe_ambiguous": ambiguous}
        if not ambiguous and candidates:
            chosen = exact_matches[0] if exact_matches else candidates[0]
            result["chosen_recipe_id"] = chosen["id"]
            result["chosen_recipe"] = {**chosen, "servings": None}
        return result

    return search_recipes


def route_after_search_recipes(state: AgentState) -> str:
    if not state["recipe_candidates"]:
        return "recipe_not_found"
    return "resolve_recipe_ambiguity" if state.get("recipe_ambiguous") else "get_recipe_ingredients"
