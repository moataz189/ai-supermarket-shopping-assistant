import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "spoonacular"


class FakeSpoonacularClient:
    """Loads recorded Spoonacular fixtures instead of making network calls."""

    def __init__(self):
        self._search_response = json.loads(
            (FIXTURES_DIR / "search_shakshuka.json").read_text()
        )
        recipe = json.loads((FIXTURES_DIR / "recipe_12345.json").read_text())
        self._recipes_by_id = {recipe["id"]: recipe}

    def search_recipes(self, query: str, number: int = 5) -> list[dict]:
        return self._search_response["results"]

    def get_recipe(self, recipe_id: int) -> dict:
        return self._recipes_by_id[recipe_id]
