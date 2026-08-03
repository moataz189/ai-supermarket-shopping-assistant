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
        expected = original_by_name[ingredient["name"]] * 2
        assert ingredient["amount"] == pytest.approx(expected)


async def test_get_recipe_ingredients_defaults_to_original_servings(mcp_server):
    fixture = _recipe_fixture()
    original_by_name = {i["name"]: i["amount"] for i in fixture["extendedIngredients"]}

    _, structured = await mcp_server.call_tool(
        "get_recipe_ingredients", {"recipe_id": fixture["id"]}
    )

    assert structured["servings"] == fixture["servings"]
    for ingredient in structured["ingredients"]:
        assert ingredient["amount"] == pytest.approx(original_by_name[ingredient["name"]])


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
