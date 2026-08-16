from fastapi.testclient import TestClient

from app.api.dependencies import get_recipe_client
from app.api.main import app
from tests.agent.fakes import FakeRecipeClient

client = TestClient(app)


def test_recipe_instructions_returns_plain_text_and_structured_steps():
    recipe_client = FakeRecipeClient(
        search_results={},
        recipes={
            1: {
                "title": "Shakshuka",
                "servings": 4,
                "ingredients": [],
                "instructions": "<ol><li>Heat oil.</li><li>Add tomatoes.</li></ol>",
                "steps": [
                    {"number": 1, "step": "Heat oil."},
                    {"number": 2, "step": "Add tomatoes."},
                ],
            }
        },
    )
    app.dependency_overrides[get_recipe_client] = lambda: recipe_client
    try:
        response = client.post("/recipe-instructions", json={"recipe_id": 1})
        assert response.status_code == 200
        body = response.json()
        assert body["recipe_id"] == 1
        assert body["instructions"] == "<ol><li>Heat oil.</li><li>Add tomatoes.</li></ol>"
        assert body["steps"] == [
            {"number": 1, "step": "Heat oil."},
            {"number": 2, "step": "Add tomatoes."},
        ]
    finally:
        app.dependency_overrides.clear()


def test_recipe_instructions_is_null_when_spoonacular_has_none_parsed():
    recipe_client = FakeRecipeClient(
        search_results={},
        recipes={2: {"title": "No Instructions Recipe", "servings": 2, "ingredients": []}},
    )
    app.dependency_overrides[get_recipe_client] = lambda: recipe_client
    try:
        response = client.post("/recipe-instructions", json={"recipe_id": 2})
        assert response.status_code == 200
        body = response.json()
        assert body["recipe_id"] == 2
        assert body["instructions"] is None
        assert body["steps"] is None
    finally:
        app.dependency_overrides.clear()


def test_recipe_instructions_404s_for_unknown_recipe_id():
    recipe_client = FakeRecipeClient(search_results={}, recipes={})
    app.dependency_overrides[get_recipe_client] = lambda: recipe_client
    try:
        response = client.post("/recipe-instructions", json={"recipe_id": 999})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
