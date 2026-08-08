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
            display_name = localize_ingredient_name(i["name"], language)
            # The tiny legacy phrase table above (app/agent/i18n.py, 6 entries) only ever
            # covered a handful of ingredients — real user report, 2026-08-08: a Hebrew
            # conversation's ingredient list showed most items in English and a few
            # (whichever happened to be in that small table) in Hebrew, an inconsistent
            # half-translated result. For a Hebrew conversation, an ingredient the big
            # dictionary *did* resolve now falls back to that same Hebrew term for display
            # too — the identical real-world grocery term already used for search, just
            # reused here rather than left English for no reason a user could tell.
            if display_name == i["name"] and language == "he" and translation["resolved"]:
                display_name = translation["hebrew_search_name"]
            items.append({
                "name": i["name"],
                "display_name": display_name,
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
