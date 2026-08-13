import os
from functools import lru_cache

from app.agent.checkpointer import get_checkpointer
from app.agent.graph import build_graph
from app.agent.ingredient_dictionary import load_ingredient_dictionary
from app.agent.llm import get_llm
from app.agent.mcp_clients import McpRecipeClient, McpRetailerCartClient, McpSupermarketDataClient


@lru_cache
def get_agent_app():
    client = McpSupermarketDataClient(
        base_url=os.environ.get("SUPERMARKET_MCP_URL", "http://localhost:8001/mcp")
    )
    recipe_client = McpRecipeClient(
        base_url=os.environ.get("RECIPE_MCP_URL", "http://localhost:8002/mcp")
    )
    retailer_cart_client = McpRetailerCartClient(
        base_url=os.environ.get("RETAILER_CART_MCP_URL", "http://localhost:8003/mcp"),
        api_key=os.environ.get("RETAILER_CART_MCP_API_KEY"),
        environment=os.environ.get("DEPLOYMENT_ENVIRONMENT", "prod"),
    )
    # Loaded once here — this function is @lru_cache'd, so the ~3.4k-entry CSV is parsed
    # exactly once per process, at (effectively) application startup, not per request.
    ingredient_dictionary = load_ingredient_dictionary()
    return build_graph(
        client,
        get_llm(),
        get_checkpointer(),
        recipe_client=recipe_client,
        retailer_cart_client=retailer_cart_client,
        ingredient_dictionary=ingredient_dictionary,
    )
