"""Unit tests for the ingredient-translation caching mechanism in
get_recipe_ingredients.py (CP9 follow-up, 2026-08-08): the Supermarket-Data MCP's
persistent cache first, LLM only for names never seen before, results written back so
the LLM is never asked twice, and a static-dict safety net if that service is
unreachable. The cache lives behind the Supermarket-Data MCP (not a direct DB
connection) since the backend/agent process has no direct SQLite access at all
(app/api/Dockerfile excludes app/db by design) — FakeSupermarketDataClient's
get_ingredient_translations/save_ingredient_translations stand in for it here.
"""

from app.agent.ingredient_translation import IngredientTranslationItem, IngredientTranslationSchema
from app.agent.nodes.get_recipe_ingredients import (
    _resolve_search_names,
    make_get_recipe_ingredients,
)
from tests.agent.fakes import FakeLLM, FakeRecipeClient, FakeSupermarketDataClient


class _BoomLLM:
    """Raises if actually invoked — used to prove a code path never calls the LLM."""

    def with_structured_output(self, schema, include_raw=False):
        return self

    async def ainvoke(self, messages):
        raise AssertionError("the LLM should not have been called for a cache hit")


class _BoomClient:
    """Raises if the translation cache is touched at all — used to prove a code path
    never reaches the Supermarket-Data MCP."""

    async def get_ingredient_translations(self, names):
        raise RuntimeError("supermarket-mcp is down")

    async def save_ingredient_translations(self, entries):
        raise AssertionError("should not attempt to save when the cache is unreachable")


async def test_seeded_cache_hit_never_calls_the_llm():
    client = FakeSupermarketDataClient({}, {})  # seed_translations=True by default

    result = await _resolve_search_names(_BoomLLM(), ["tomatoes"], client)

    assert result == {"tomatoes": "עגבניה"}


async def test_unseen_ingredient_uses_the_llm_and_gets_cached_for_next_time():
    client = FakeSupermarketDataClient({}, {}, seed_translations=False)
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[
        IngredientTranslationItem(original_name="pasta", search_name_he="פסטה"),
    ]))

    result = await _resolve_search_names(llm, ["pasta"], client)
    assert result == {"pasta": "פסטה"}

    # A second lookup must hit the now-populated cache, not the LLM again.
    second_result = await _resolve_search_names(_BoomLLM(), ["pasta"], client)
    assert second_result == {"pasta": "פסטה"}


async def test_mixed_cache_hit_and_miss_only_translates_the_miss():
    client = FakeSupermarketDataClient({}, {})  # "tomatoes" is seeded
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[
        IngredientTranslationItem(original_name="pasta", search_name_he="פסטה"),
    ]))

    result = await _resolve_search_names(llm, ["tomatoes", "pasta"], client)

    assert result == {"tomatoes": "עגבניה", "pasta": "פסטה"}


async def test_case_and_whitespace_variants_share_one_cache_entry():
    client = FakeSupermarketDataClient({}, {}, seed_translations=False)
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[
        IngredientTranslationItem(original_name="Heavy Cream", search_name_he="שמנת מתוקה"),
    ]))

    await _resolve_search_names(llm, ["Heavy Cream"], client)
    # Different casing/whitespace, same underlying ingredient — must hit the cache, not
    # call the (here, exception-raising) LLM again.
    result = await _resolve_search_names(_BoomLLM(), ["  heavy cream  "], client)

    assert result == {"  heavy cream  ": "שמנת מתוקה"}


async def test_translation_service_unavailable_falls_back_to_static_translations():
    result = await _resolve_search_names(_BoomLLM(), ["tomatoes", "onion", "pasta"], _BoomClient())

    # tomatoes/onion are in the small static INGREDIENT_TRANSLATIONS safety net
    # (app/agent/i18n.py); pasta isn't, and there's no deterministic fallback for it.
    assert result == {"tomatoes": "עגבניה", "onion": "בצל"}


async def test_empty_ingredient_list_never_touches_the_client_or_llm():
    result = await _resolve_search_names(_BoomLLM(), [], _BoomClient())

    assert result == {}


async def test_llm_translation_with_no_usable_result_leaves_that_name_unresolved():
    client = FakeSupermarketDataClient({}, {}, seed_translations=False)
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[]))

    result = await _resolve_search_names(llm, ["a very obscure ingredient"], client)

    assert result == {}


async def test_node_level_items_carry_the_resolved_search_name():
    recipe_client = FakeRecipeClient(
        search_results={"shakshuka": [{"id": 1, "title": "Shakshuka"}]},
        recipes={
            1: {
                "title": "Shakshuka",
                "servings": 4,
                "ingredients": [
                    {"name": "tomatoes", "amount": 400.0, "unit": "g"},
                    {"name": "pasta", "amount": 200.0, "unit": "g"},
                ],
            }
        },
    )
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[
        IngredientTranslationItem(original_name="pasta", search_name_he="פסטה"),
    ]))
    # Seeded (default), so "tomatoes" resolves from the persistent cache and only
    # "pasta" needs the LLM — exercises the mixed hit/miss path at the node level.
    client = FakeSupermarketDataClient({}, {})
    node = make_get_recipe_ingredients(recipe_client, llm, client)
    state = {
        "parsed_request": {"servings": 4, "language": "en"},
        "chosen_recipe_id": 1,
    }

    result = await node(state)

    items_by_name = {i["name"]: i for i in result["parsed_request"]["items"]}
    assert items_by_name["tomatoes"]["search_name"] == "עגבניה"  # from the seeded cache
    assert items_by_name["pasta"]["search_name"] == "פסטה"  # from the LLM fallback


async def test_node_level_unresolved_ingredient_falls_back_to_its_own_english_name():
    recipe_client = FakeRecipeClient(
        search_results={"mystery": [{"id": 1, "title": "Mystery"}]},
        recipes={
            1: {
                "title": "Mystery",
                "servings": 2,
                "ingredients": [{"name": "an obscure spice", "amount": 1.0, "unit": "pinch"}],
            }
        },
    )
    llm = FakeLLM(parsed=IngredientTranslationSchema(translations=[]))
    client = FakeSupermarketDataClient({}, {}, seed_translations=False)
    node = make_get_recipe_ingredients(recipe_client, llm, client)
    state = {
        "parsed_request": {"servings": 2, "language": "en"},
        "chosen_recipe_id": 1,
    }

    result = await node(state)

    item = result["parsed_request"]["items"][0]
    assert item["search_name"] == "an obscure spice"
