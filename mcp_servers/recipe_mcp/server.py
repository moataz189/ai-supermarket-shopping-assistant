from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_servers.recipe_mcp.ingredient_defaults import (
    default_quantity_for,
    is_non_actionable_unit,
)
from mcp_servers.recipe_mcp.quantity import is_precise_metric_unit
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
        raw_ingredients = data["extendedIngredients"]

        # Fetched at most once per call, and only if at least one ingredient actually
        # needs it (see the loop below) -- never once per ingredient, never when every
        # ingredient's own measures.metric is already precise.
        widget_by_name: dict[str, dict] | None = None

        def _widget_lookup(name: str) -> dict | None:
            nonlocal widget_by_name
            if widget_by_name is None:
                widget = client.get_ingredient_widget(recipe_id)
                widget_by_name = {
                    w["name"].strip().lower(): w["amount"]["metric"] for w in widget["ingredients"]
                }
            return widget_by_name.get(name.strip().lower())

        ingredients = []
        for i in raw_ingredients:
            original_amount, original_unit = i["amount"], i["unit"]
            metric = ((i.get("measures") or {}).get("metric")) or {}
            metric_amount, metric_unit = metric.get("amount"), metric.get("unitShort")

            if is_precise_metric_unit(metric_unit):
                amount, unit = metric_amount, metric_unit
            else:
                widget_entry = _widget_lookup(i["name"])
                if widget_entry is not None and is_precise_metric_unit(widget_entry.get("unit")):
                    amount, unit = widget_entry["value"], widget_entry["unit"]
                else:
                    # Neither Spoonacular's own metric measure nor the ingredient
                    # widget has a deterministic weight/volume for this ingredient
                    # (e.g. a whole egg) -- gracefully fall back to the recipe's
                    # original amount/unit rather than guessing.
                    amount, unit = original_amount, original_unit

            final_amount, final_unit = amount * ratio, unit
            if is_non_actionable_unit(final_unit):
                # A "servings" count (or no unit at all) is not a real, buyable
                # quantity — confirmed live (Spoonacular id 652061, "Miso Cream Pasta")
                # that this happens when Spoonacular has no parseable amount for an
                # ingredient anywhere, in either endpoint. Use a data-driven default
                # instead of literally buying `final_amount` units of it (see
                # ingredient_defaults.py); an ingredient not in any default table keeps
                # this (unhelpful, but honest) placeholder as a last resort.
                default = default_quantity_for(i["name"], target_servings)
                if default is not None:
                    final_amount, final_unit = default

            ingredients.append(Ingredient(
                name=i["name"],
                amount=final_amount,
                unit=final_unit,
                original_amount=original_amount * ratio,
                original_unit=original_unit,
            ))

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
