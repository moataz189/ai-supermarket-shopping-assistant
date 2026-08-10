import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "spoonacular"


class FakeSpoonacularClient:
    """Loads recorded Spoonacular fixtures instead of making network calls.

    `widget_calls` counts get_ingredient_widget invocations -- tests use it to prove the
    widget is only fetched when at least one ingredient's measures.metric isn't already
    precise (see mcp_servers/recipe_mcp/quantity.py's is_precise_metric_unit), and fetched
    at most once per get_recipe_ingredients call, never once per ingredient.
    """

    def __init__(self):
        self._search_response = json.loads(
            (FIXTURES_DIR / "search_shakshuka.json").read_text()
        )
        recipe = json.loads((FIXTURES_DIR / "recipe_12345.json").read_text())
        self._recipes_by_id = {recipe["id"]: recipe}
        self._widgets_by_id = {
            654959: json.loads((FIXTURES_DIR / "ingredient_widget_654959.json").read_text())
        }
        self.widget_calls = 0

    def search_recipes(self, query: str, number: int = 5) -> list[dict]:
        return self._search_response["results"]

    def get_recipe(self, recipe_id: int) -> dict:
        return self._recipes_by_id[recipe_id]

    def get_ingredient_widget(self, recipe_id: int) -> dict:
        self.widget_calls += 1
        return self._widgets_by_id[recipe_id]
