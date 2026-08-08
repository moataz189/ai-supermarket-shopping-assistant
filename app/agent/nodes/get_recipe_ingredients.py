from app.agent.i18n import localize_ingredient_name
from app.agent.ingredient_translation import translate_ingredients_to_hebrew
from app.agent.state import AgentState


def _static_fallback(names: list[str]) -> dict[str, str]:
    """Last-resort translation, used only if the Supermarket-Data MCP's ingredient-
    translation cache is unreachable at all (network error, service down, etc.) — the
    small, already-verified INGREDIENT_TRANSLATIONS table (app/agent/i18n.py) that
    predates the persistent cache. Keeps the previously-shipped, already-working
    translations (tomatoes, milk, onion...) functional even if that service is
    temporarily broken, instead of silently regressing all the way back to unqualified
    English names."""
    return {
        name: translated
        for name in names
        if (translated := localize_ingredient_name(name, "he")) != name
    }


async def _resolve_search_names(llm, names: list[str], client) -> dict[str, str]:
    """English ingredient name -> Hebrew catalog search term, using the Supermarket-Data
    MCP's persistent cache first (get_ingredient_translations/save_ingredient_translations
    — see mcp_servers/supermarket_mcp/server.py) and the LLM only for names never seen
    before — per explicit product decision, the LLM is a fallback, not the primary
    mechanism. If that service itself is unreachable, falls back to `_static_fallback`
    rather than an empty result, so an outage doesn't regress already-working,
    previously-verified translations back to raw English.

    Deliberately talks to the Supermarket-Data MCP over the existing `client` (the same
    one used for product search elsewhere in the graph) rather than the DB directly —
    the backend/agent process has no direct SQLite access at all (app/api/Dockerfile
    excludes app/db from that image by design); only supermarket-mcp does.
    """
    if not names:
        return {}

    try:
        cached = await client.get_ingredient_translations(names)
        resolved = dict(cached)
        unseen = [name for name in names if name not in resolved]
        if unseen:
            translated = await translate_ingredients_to_hebrew(llm, unseen)
            new_entries = [
                {"name": name, "search_name_he": translated[name]}
                for name in unseen
                if translated.get(name)
            ]
            if new_entries:
                await client.save_ingredient_translations(new_entries)
                resolved.update({e["name"]: e["search_name_he"] for e in new_entries})
        return resolved
    except Exception:
        return _static_fallback(names)


def make_get_recipe_ingredients(recipe_client, llm, client):
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
        # catalog search query always tries Hebrew, entirely independent of
        # `display_name` below, which is user-facing and follows the conversation's own
        # language. A small, already-verified set of common terms is seeded into the
        # cache at startup; anything else is translated once via the LLM and cached for
        # every future request (app/agent/ingredient_translation.py).
        search_names = await _resolve_search_names(llm, [i["name"] for i in raw_ingredients], client)

        items = [
            {
                "name": i["name"],
                "display_name": localize_ingredient_name(i["name"], language),
                # Falls back to the canonical English name (matching display_name's own
                # fallback) when no translation was found or resolvable.
                "search_name": search_names.get(i["name"], i["name"]),
                "quantity": i["amount"],
                "unit": i["unit"],
            }
            for i in raw_ingredients
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
