from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.agent.nodes.parse_request import ParsedRequestSchema
from tests.agent.fakes import FakeLLM, FakeRecipeClient, FakeSupermarketDataClient


async def test_recipe_search_with_zero_results_returns_graceful_warning_not_crash():
    """Reproduces a live bug: a real Spoonacular search that legitimately returns zero
    results (confirmed via a direct API call during CP9 live verification) crashed
    get_recipe_ingredients with IndexError on `recipe_candidates[0]`, because nothing
    upstream ever checked for the empty-candidates case."""
    llm = FakeLLM(
        ParsedRequestSchema(request_type="recipe", recipe_query="nonexistent dish", items=[])
    )
    recipe_client = FakeRecipeClient(search_results={}, recipes={})
    client = FakeSupermarketDataClient({}, {})
    app = build_graph(client, llm, MemorySaver(), recipe_client=recipe_client)
    config = {"configurable": {"thread_id": "t1"}}

    result = await app.ainvoke({"raw_message": "make me a nonexistent dish"}, config=config)

    assert "__interrupt__" not in result
    assert result["recipe_candidates"] == []
    assert result["status"] == "partial_success"
    assert result["warnings"] == [{"code": "recipe_not_found", "query": "nonexistent dish"}]
    assert result["final_result"]["carts"] == {}
    assert result["final_result"]["chosen_retailer"] is None
