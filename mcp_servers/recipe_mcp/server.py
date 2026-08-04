from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_servers.recipe_mcp.schemas import (
    GetRecipeIngredientsResponse,
    Ingredient,
    RecipeDetail,
    RecipeSummary,
    SearchRecipesResponse,
)
from mcp_servers.recipe_mcp.spoonacular_client import SpoonacularClient


def create_server(client) -> FastMCP:
    # FastMCP auto-enables DNS-rebinding protection restricted to localhost (captured at
    # construction time, before __main__ rebinds host to 0.0.0.0 below) — docker-compose
    # peers reach this server as "recipe-mcp", which the localhost-only default would
    # reject with 421 Misdirected Request, so that hostname must be allowed explicitly.
    mcp = FastMCP(
        "recipe",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "recipe-mcp:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        ),
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.tool()
    def search_recipes(query: str) -> SearchRecipesResponse:
        results = client.search_recipes(query)
        return SearchRecipesResponse(
            recipes=[RecipeSummary(id=r["id"], title=r["title"]) for r in results]
        )

    @mcp.tool()
    def get_recipe(recipe_id: int) -> RecipeDetail:
        data = client.get_recipe(recipe_id)
        return RecipeDetail(id=data["id"], title=data["title"], servings=data["servings"])

    @mcp.tool()
    def get_recipe_ingredients(
        recipe_id: int, servings: int | None = None
    ) -> GetRecipeIngredientsResponse:
        data = client.get_recipe(recipe_id)
        original_servings = data["servings"]
        if original_servings <= 0:
            raise ValueError(
                f"recipe {recipe_id} has a non-positive original servings count: "
                f"{original_servings}"
            )

        target_servings = original_servings if servings is None else servings
        if target_servings <= 0:
            raise ValueError(f"servings must be a positive integer, got {target_servings}")

        ratio = target_servings / original_servings
        ingredients = [
            Ingredient(name=i["name"], amount=i["amount"] * ratio, unit=i["unit"])
            for i in data["extendedIngredients"]
        ]
        return GetRecipeIngredientsResponse(
            recipe_id=recipe_id, servings=target_servings, ingredients=ingredients
        )

    return mcp


if __name__ == "__main__":
    import os

    mcp = create_server(SpoonacularClient())
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8002"))
    mcp.run(transport="streamable-http")
