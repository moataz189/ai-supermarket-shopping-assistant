from app.agent.i18n import localize_ingredient_name
from app.agent.ingredient_dictionary import translate_ingredient
from app.agent.state import AgentState


def make_get_recipe_ingredients(recipe_client, ingredient_dictionary: dict[str, str]):
    async def get_recipe_ingredients(state: AgentState) -> AgentState:
        parsed = state["parsed_request"]
        recipe_id = state.get("chosen_recipe_id") or state["recipe_candidates"][0]["id"]
        servings = parsed.get("servings")
        language = parsed.get("language", "en")

        result = await recipe_client.get_recipe_ingredients(recipe_id, servings)
        raw_ingredients = result["ingredients"]

        # The real Shufersal/Rami Levy catalog is Hebrew-only regardless of what language
        # *this conversation* is in (confirmed live: an English-language recipe request
        # still needs "tomatoes" searched for as "עגבניה", not "tomatoes") — so the
        # catalog search query always tries the dictionary's Hebrew term, entirely
        # independent of `display_name` below, which is user-facing and follows the
        # conversation's own language. Each ingredient carries its own normalized
        # translation object (english_name/hebrew_search_name/resolved) rather than a
        # bare string, so downstream nodes and logs can always tell a genuine dictionary
        # match apart from an unresolved English fallback.
        items = []
        for i in raw_ingredients:
            translation = translate_ingredient(ingredient_dictionary, i["name"])
            items.append({
                "name": i["name"],
                "display_name": localize_ingredient_name(i["name"], language),
                "search_name": translation["hebrew_search_name"],
                "english_name": translation["english_name"],
                "translation_resolved": translation["resolved"],
                "quantity": i["amount"],
                "unit": i["unit"],
            })

        chosen_recipe = dict(state.get("chosen_recipe") or {"id": recipe_id})
        # `result["servings"]` is what the ingredients above are portioned for; it equals the
        # recipe's true original serving count whenever the user didn't request an override.
        chosen_recipe["servings"] = result.get("servings")

        return {
            "parsed_request": {**parsed, "items": items},
            "chosen_recipe": chosen_recipe,
        }

    return get_recipe_ingredients
