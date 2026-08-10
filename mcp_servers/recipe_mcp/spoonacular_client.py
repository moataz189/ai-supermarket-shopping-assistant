import os

import httpx

BASE_URL = "https://api.spoonacular.com"
DEFAULT_TIMEOUT = 10.0


class SpoonacularClient:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        self.api_key = api_key or os.environ["SPOONACULAR_API_KEY"]
        self.client = client or httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT)

    def search_recipes(self, query: str, number: int = 5) -> list[dict]:
        response = self.client.get(
            "/recipes/complexSearch",
            params={"query": query, "number": number, "apiKey": self.api_key},
        )
        response.raise_for_status()
        return response.json()["results"]

    def get_recipe(self, recipe_id: int) -> dict:
        response = self.client.get(
            f"/recipes/{recipe_id}/information", params={"apiKey": self.api_key}
        )
        response.raise_for_status()
        return response.json()

    def get_ingredient_widget(self, recipe_id: int) -> dict:
        response = self.client.get(
            f"/recipes/{recipe_id}/ingredientWidget.json", params={"apiKey": self.api_key}
        )
        response.raise_for_status()
        return response.json()
