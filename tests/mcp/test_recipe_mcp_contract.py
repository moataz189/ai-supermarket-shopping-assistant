import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from mcp_servers.recipe_mcp import server
from tests.mcp.fakes import FIXTURES_DIR, FakeSpoonacularClient


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def _blocked_send(*args, **kwargs):
        raise AssertionError("attempted a real network call during tests")

    monkeypatch.setattr(httpx.Client, "send", _blocked_send)


@pytest.fixture
def mcp_server():
    return server.create_server(FakeSpoonacularClient())


def _search_fixture():
    return json.loads((FIXTURES_DIR / "search_shakshuka.json").read_text())


def _recipe_fixture():
    return json.loads((FIXTURES_DIR / "recipe_12345.json").read_text())


async def test_search_recipes_returns_candidates(mcp_server):
    fixture = _search_fixture()

    _, structured = await mcp_server.call_tool("search_recipes", {"query": "shakshuka"})

    assert structured["recipes"]
    assert len(structured["recipes"]) == len(fixture["results"])
    for recipe in structured["recipes"]:
        assert "id" in recipe
        assert "title" in recipe


async def test_get_recipe_returns_servings(mcp_server):
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool("get_recipe", {"recipe_id": fixture["id"]})

    assert structured["id"] == fixture["id"]
    assert structured["title"] == fixture["title"]
    assert structured["servings"] == fixture["servings"]


async def test_get_recipe_instructions_returns_plain_text_and_structured_steps(mcp_server):
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_instructions", {"recipe_id": fixture["id"]}
    )

    assert structured["recipe_id"] == fixture["id"]
    assert structured["instructions"] == fixture["instructions"]
    assert [s["step"] for s in structured["steps"]] == [
        s["step"] for s in fixture["analyzedInstructions"][0]["steps"]
    ]


async def test_get_recipe_instructions_flattens_multiple_named_sections(mcp_server):
    # A handful of real recipes split analyzedInstructions into several named sections
    # (e.g. "For the sauce" / "For the pasta") -- flattened in Spoonacular's own given
    # order, since nothing downstream needs the section grouping.
    client = FakeSpoonacularClient()
    client._recipes_by_id[999] = {
        "id": 999,
        "title": "Two-Part Recipe",
        "servings": 2,
        "instructions": "<ol><li>Make the sauce.</li><li>Make the pasta.</li></ol>",
        "analyzedInstructions": [
            {"name": "Sauce", "steps": [{"number": 1, "step": "Simmer the tomatoes."}]},
            {"name": "Pasta", "steps": [{"number": 1, "step": "Boil the pasta."}]},
        ],
        "extendedIngredients": [],
    }
    server_with_extra_recipe = server.create_server(client)

    _, structured = await server_with_extra_recipe.call_tool(
        "get_recipe_instructions", {"recipe_id": 999}
    )

    assert [s["step"] for s in structured["steps"]] == ["Simmer the tomatoes.", "Boil the pasta."]


async def test_get_recipe_instructions_is_none_when_spoonacular_has_none_parsed(mcp_server):
    # Real, documented Spoonacular case: instructions/analyzedInstructions can both be
    # empty for a recipe Spoonacular hasn't parsed instructions for -- not an error.
    client = FakeSpoonacularClient()
    client._recipes_by_id[888] = {
        "id": 888,
        "title": "No Instructions Recipe",
        "servings": 2,
        "instructions": "",
        "analyzedInstructions": [],
        "extendedIngredients": [],
    }
    server_with_extra_recipe = server.create_server(client)

    _, structured = await server_with_extra_recipe.call_tool(
        "get_recipe_instructions", {"recipe_id": 888}
    )

    assert structured["instructions"] is None
    assert structured["steps"] is None


async def test_get_recipe_ingredients_scales_amounts(mcp_server):
    fixture = _recipe_fixture()
    doubled_servings = fixture["servings"] * 2
    original_by_name = {i["name"]: i["amount"] for i in fixture["extendedIngredients"]}

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"], "servings": doubled_servings}
    )

    assert structured["servings"] == doubled_servings
    assert len(structured["ingredients"]) == len(fixture["extendedIngredients"])
    for ingredient in structured["ingredients"]:
        expected_original = original_by_name[ingredient["name"]] * 2
        assert ingredient["original_amount"] == pytest.approx(expected_original)
    tomatoes = next(i for i in structured["ingredients"] if i["name"] == "tomatoes")
    assert tomatoes["amount"] == pytest.approx(800.0)  # 400 g normalized x2 servings


async def test_get_recipe_ingredients_defaults_to_original_servings(mcp_server):
    fixture = _recipe_fixture()
    original_by_name = {i["name"]: i["amount"] for i in fixture["extendedIngredients"]}

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    assert structured["servings"] == fixture["servings"]
    for ingredient in structured["ingredients"]:
        assert ingredient["original_amount"] == pytest.approx(original_by_name[ingredient["name"]])


async def test_tomatoes_use_the_precise_metric_measure_directly():
    # Note: this recipe's "eggs" entry (processed first) is itself imprecise and does
    # trigger the shared widget fetch on its own -- that's covered by
    # test_widget_is_fetched_at_most_once_even_with_multiple_imprecise_ingredients and
    # test_no_widget_call_at_all_when_every_ingredient_is_already_precise below. This
    # test only proves tomatoes' own value came from measures.metric, not the widget
    # (the widget's tomatoes entry is intentionally identical, so a value-only
    # assertion can't distinguish the two on its own -- see the dedicated
    # zero-widget-calls test for that proof).
    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    tomatoes = next(i for i in structured["ingredients"] if i["name"] == "tomatoes")
    assert tomatoes["amount"] == pytest.approx(400.0)
    assert tomatoes["unit"] == "g"
    assert tomatoes["original_amount"] == pytest.approx(14.0)
    assert tomatoes["original_unit"] == "ounces"


async def test_olive_oil_precise_metric_scales_with_servings_matching_the_spec_example():
    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"], "servings": fixture["servings"] * 2}
    )

    olive_oil = next(i for i in structured["ingredients"] if i["name"] == "olive oil")
    assert olive_oil["amount"] == pytest.approx(60.0)  # 30 ml x2 servings
    assert olive_oil["unit"] == "ml"


class _AllPreciseClient:
    """Stub client for a recipe where every ingredient's own measures.metric is already
    precise -- isolates the "never calls the widget at all when nothing needs it" case
    from the shared recipe_12345 fixture, where eggs/onion legitimately do need it."""

    def __init__(self):
        self.widget_calls = 0

    def search_recipes(self, query: str, number: int = 5) -> list[dict]:
        raise NotImplementedError

    def get_recipe(self, recipe_id: int) -> dict:
        return {
            "id": recipe_id,
            "title": "All Precise",
            "servings": 2,
            "extendedIngredients": [
                {
                    "name": "tomatoes", "amount": 14.0, "unit": "ounces",
                    "measures": {"metric": {"amount": 400.0, "unitShort": "g"}},
                },
                {
                    "name": "olive oil", "amount": 2.0, "unit": "tbsp",
                    "measures": {"metric": {"amount": 30.0, "unitShort": "ml"}},
                },
            ],
        }

    def get_ingredient_widget(self, recipe_id: int) -> dict:
        self.widget_calls += 1
        raise AssertionError("should never be called when every ingredient is precise")


async def test_no_widget_call_at_all_when_every_ingredient_is_already_precise():
    fake_client = _AllPreciseClient()
    mcp_server = server.create_server(fake_client)

    _, structured = await mcp_server.call_tool("get_recipe_ingredients", {"recipe_id": 1})

    assert fake_client.widget_calls == 0
    tomatoes = next(i for i in structured["ingredients"] if i["name"] == "tomatoes")
    assert tomatoes["amount"] == pytest.approx(400.0)


async def test_imprecise_metric_measure_falls_back_to_the_ingredient_widget():
    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    onion = next(i for i in structured["ingredients"] if i["name"] == "onion")
    assert onion["amount"] == pytest.approx(110.0)
    assert onion["unit"] == "g"
    assert onion["original_amount"] == pytest.approx(1.0)
    assert onion["original_unit"] == "medium"
    assert fake_client.widget_calls == 1  # onion needed it


async def test_widget_is_fetched_at_most_once_even_with_multiple_imprecise_ingredients():
    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    await mcp_server.call_tool("get_recipe_ingredients", {"recipe_id": fixture["id"]})

    # onion AND eggs are both imprecise in measures.metric -- still exactly one call.
    assert fake_client.widget_calls == 1


async def test_ingredient_with_no_usable_metric_anywhere_gracefully_falls_back_to_original():
    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    # eggs: measures.metric is "4 large" (not precise) AND the widget's own entry is
    # also "4 large" (Spoonacular has no deterministic weight for a whole egg) -- falls
    # all the way back to the recipe's original amount/unit, unchanged.
    eggs = next(i for i in structured["ingredients"] if i["name"] == "eggs")
    assert eggs["amount"] == pytest.approx(4.0)
    assert eggs["unit"] == "large"
    assert eggs["original_amount"] == pytest.approx(4.0)
    assert eggs["original_unit"] == "large"


async def test_widget_lookup_scales_by_the_same_servings_ratio_as_everything_else():
    fake_client = FakeSpoonacularClient()
    mcp_server = server.create_server(fake_client)
    fixture = _recipe_fixture()

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"], "servings": fixture["servings"] * 2}
    )

    onion = next(i for i in structured["ingredients"] if i["name"] == "onion")
    assert onion["amount"] == pytest.approx(220.0)  # 110 g x2 servings


async def test_get_recipe_ingredients_rejects_non_positive_requested_servings(mcp_server):
    fixture = _recipe_fixture()

    with pytest.raises(ToolError, match="servings"):
        await mcp_server.call_tool(
            "get_recipe_ingredients", {"recipe_id": fixture["id"], "servings": 0}
        )


class _ZeroServingsClient:
    """Stub client simulating a recipe record with an invalid (non-positive) servings count."""

    def __init__(self):
        recipe = _recipe_fixture()
        self._recipe = {**recipe, "servings": 0}

    def search_recipes(self, query: str, number: int = 5) -> list[dict]:
        raise NotImplementedError

    def get_recipe(self, recipe_id: int) -> dict:
        return self._recipe


async def test_get_recipe_ingredients_rejects_non_positive_original_servings():
    fixture = _recipe_fixture()
    zero_servings_server = server.create_server(_ZeroServingsClient())

    with pytest.raises(ToolError, match="servings"):
        await zero_servings_server.call_tool(
            "get_recipe_ingredients", {"recipe_id": fixture["id"]}
        )


class _ServingsPlaceholderClient:
    """Stub client for ingredients whose only available quantity anywhere (both
    measures.metric and the ingredientWidget) is a meaningless "servings" placeholder --
    a real Spoonacular data-completeness gap, confirmed live against recipe 652061 ("Miso
    Cream Pasta"). Isolates the ingredient-defaults override (see
    mcp_servers/recipe_mcp/ingredient_defaults.py) from the shared recipe_12345 fixture.
    """

    def __init__(self):
        self.widget_calls = 0

    def search_recipes(self, query: str, number: int = 5) -> list[dict]:
        raise NotImplementedError

    def get_recipe(self, recipe_id: int) -> dict:
        return {
            "id": recipe_id,
            "title": "Servings Placeholder Test",
            "servings": 1,
            "extendedIngredients": [
                {"name": "olive oil", "amount": 1.0, "unit": "serving",
                 "measures": {"metric": {"amount": 1.0, "unitShort": "serving"}}},
                {"name": "pasta", "amount": 1.0, "unit": "serving",
                 "measures": {"metric": {"amount": 1.0, "unitShort": "serving"}}},
                {"name": "onion", "amount": 1.0, "unit": "",
                 "measures": {"metric": {"amount": 1.0, "unitShort": ""}}},
                {"name": "tomatoes", "amount": 1.0, "unit": "serving",
                 "measures": {"metric": {"amount": 1.0, "unitShort": "serving"}}},
                {"name": "shiso leaves", "amount": 9.0, "unit": "servings",
                 "measures": {"metric": {"amount": 9.0, "unitShort": "servings"}}},
            ],
        }

    def get_ingredient_widget(self, recipe_id: int) -> dict:
        self.widget_calls += 1
        return {"ingredients": [
            {"name": "olive oil", "amount": {"metric": {"value": 1.0, "unit": "serving"}}},
            {"name": "pasta", "amount": {"metric": {"value": 1.0, "unit": "serving"}}},
            {"name": "onion", "amount": {"metric": {"value": 1.0, "unit": ""}}},
            {"name": "tomatoes", "amount": {"metric": {"value": 1.0, "unit": "serving"}}},
            {"name": "shiso leaves", "amount": {"metric": {"value": 9.0, "unit": "servings"}}},
        ]}


async def test_non_actionable_servings_unit_uses_the_ingredient_default_table():
    fake_client = _ServingsPlaceholderClient()
    mcp_server = server.create_server(fake_client)

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": 1, "servings": 4}
    )
    by_name = {i["name"]: i for i in structured["ingredients"]}

    assert by_name["olive oil"]["amount"] == pytest.approx(60.0)
    assert by_name["olive oil"]["unit"] == "ml"
    assert by_name["pasta"]["amount"] == pytest.approx(500.0)
    assert by_name["pasta"]["unit"] == "g"
    assert by_name["onion"]["amount"] == pytest.approx(1.0)
    assert by_name["onion"]["unit"] == "unit"
    assert by_name["tomatoes"]["amount"] == pytest.approx(0.5)
    assert by_name["tomatoes"]["unit"] == "kg"
    # Not in either default table -- never resolves to the raw, meaningless "36
    # servings" (9 x4) -- falls back to the same safe "buy 1" default as a known
    # unit-sold item.
    assert by_name["shiso leaves"]["amount"] == pytest.approx(1.0)
    assert by_name["shiso leaves"]["unit"] == "unit"


async def test_unit_default_ignores_the_servings_count_entirely():
    # "onion" moved into PER_SERVING_DEFAULTS (see the test below) -- "shiso leaves" has
    # no table entry at all, so it's still the flat "buy 1" fallback this test covers.
    fake_client = _ServingsPlaceholderClient()
    mcp_server = server.create_server(fake_client)

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": 1, "servings": 20}
    )

    shiso = next(i for i in structured["ingredients"] if i["name"] == "shiso leaves")
    assert shiso["amount"] == pytest.approx(1.0)  # still just 1, regardless of servings


async def test_onion_per_serving_default_scales_with_servings():
    # Real user report: a 40-serving recipe still showed a flat "1 unit" of onion --
    # onion now has a real per-serving count in PER_SERVING_DEFAULTS (0.25/serving), so
    # this must scale like any other per-serving default, not stay flat.
    fake_client = _ServingsPlaceholderClient()
    mcp_server = server.create_server(fake_client)

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": 1, "servings": 20}
    )

    onion = next(i for i in structured["ingredients"] if i["name"] == "onion")
    assert onion["amount"] == pytest.approx(5.0)  # 0.25 x 20 servings
    assert onion["unit"] == "unit"


async def test_weight_default_ignores_the_servings_count_entirely():
    fake_client = _ServingsPlaceholderClient()
    mcp_server = server.create_server(fake_client)

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": 1, "servings": 20}
    )

    tomatoes = next(i for i in structured["ingredients"] if i["name"] == "tomatoes")
    assert tomatoes["amount"] == pytest.approx(0.5)  # flat default, not scaled
