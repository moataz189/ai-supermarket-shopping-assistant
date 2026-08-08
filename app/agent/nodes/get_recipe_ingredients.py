from app.agent.i18n import localize_ingredient_name
from app.agent.state import AgentState


def make_get_recipe_ingredients(recipe_client):
    async def get_recipe_ingredients(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        recipe_id = state.get("chosen_recipe_id") or state["recipe_candidates"][0]["id"]
        servings = parsed.get("servings")
        language = parsed.get("language", "en")

        result = await recipe_client.get_recipe_ingredients(recipe_id, servings)
        items = [
            {
                "name": i["name"],
                "display_name": localize_ingredient_name(i["name"], language),
                # The real Shufersal/Rami Levy catalog is Hebrew-only regardless of what
                # language *this conversation* is in (confirmed live: an English-language
                # recipe request still needs "tomatoes" searched for as "עגבניה", not
                # "tomatoes") — so the catalog search query always tries Hebrew, entirely
                # independent of `display_name`, which is user-facing and follows the
                # conversation's own language. Falls back to the canonical English name
                # (matching display_name's own fallback) when no translation exists.
                "search_name": localize_ingredient_name(i["name"], "he"),
                "quantity": i["amount"],
                "unit": i["unit"],
            }
            for i in result["ingredients"]
        ]

        chosen_recipe = dict(state.get("chosen_recipe") or {"id": recipe_id})
        # `result["servings"]` is what the ingredients above are portioned for; it equals the
        # recipe's true original serving count whenever the user didn't request an override.
        chosen_recipe["servings"] = result.get("servings")

        return {
            "parsed_request": {**parsed, "items": items},
            "chosen_recipe": chosen_recipe,
        }

    return get_recipe_ingredients
