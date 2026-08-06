from langgraph.graph import END, START, StateGraph

from app.agent.nodes.build_retailer_cart import make_build_retailer_cart
from app.agent.nodes.choose_retailer import choose_retailer
from app.agent.nodes.finalize import finalize
from app.agent.nodes.get_recipe_ingredients import make_get_recipe_ingredients
from app.agent.nodes.parse_request import make_parse_request
from app.agent.nodes.prepare_retailer_cart import make_prepare_retailer_cart
from app.agent.nodes.recipe_not_found import recipe_not_found
from app.agent.nodes.resolve_ambiguity import resolve_ambiguity, route_after_resolve
from app.agent.nodes.resolve_items import make_resolve_items
from app.agent.nodes.resolve_recipe_ambiguity import resolve_recipe_ambiguity
from app.agent.nodes.search_recipes import make_search_recipes, route_after_search_recipes
from app.agent.state import AgentState


def route_after_parse(state: AgentState) -> str:
    if state["parsed_request"]["request_type"] == "recipe":
        return "search_recipes"
    return "resolve_items"


def route_after_choice(state: AgentState) -> str:
    return "prepare_retailer_cart" if state.get("chosen_retailer") else "finalize"


def build_graph(client, llm, checkpointer, recipe_client=None, retailer_cart_client=None):
    """`recipe_client` is optional so grocery-list-only callers (including CP4's existing
    tests) don't need to supply one — it's only ever used on the recipe branch, reached
    solely when `request_type == "recipe"`. `retailer_cart_client` is optional the same
    way — it's only ever used once the user has actually chosen a retailer (CP4)."""
    graph = StateGraph(AgentState)
    graph.add_node("parse_request", make_parse_request(llm))
    graph.add_node("search_recipes", make_search_recipes(recipe_client))
    graph.add_node("recipe_not_found", recipe_not_found)
    graph.add_node("resolve_recipe_ambiguity", resolve_recipe_ambiguity)
    graph.add_node("get_recipe_ingredients", make_get_recipe_ingredients(recipe_client))
    graph.add_node("resolve_items", make_resolve_items(client))
    graph.add_node("resolve_ambiguity", resolve_ambiguity)
    graph.add_node("build_shufersal_cart", make_build_retailer_cart("shufersal", client))
    graph.add_node("build_rami_levy_cart", make_build_retailer_cart("rami_levy", client))
    graph.add_node("choose_retailer", choose_retailer)
    graph.add_node("prepare_retailer_cart", make_prepare_retailer_cart(retailer_cart_client))
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "parse_request")
    graph.add_conditional_edges(
        "parse_request", route_after_parse, ["search_recipes", "resolve_items"]
    )
    graph.add_conditional_edges(
        "search_recipes",
        route_after_search_recipes,
        ["recipe_not_found", "resolve_recipe_ambiguity", "get_recipe_ingredients"],
    )
    graph.add_edge("recipe_not_found", END)
    graph.add_edge("resolve_recipe_ambiguity", "get_recipe_ingredients")
    graph.add_edge("get_recipe_ingredients", "resolve_items")
    graph.add_conditional_edges(
        "resolve_items", route_after_resolve, ["resolve_ambiguity", "build_shufersal_cart"]
    )
    graph.add_edge("resolve_ambiguity", "resolve_items")
    graph.add_edge("build_shufersal_cart", "build_rami_levy_cart")
    graph.add_edge("build_rami_levy_cart", "choose_retailer")
    graph.add_conditional_edges(
        "choose_retailer", route_after_choice, ["prepare_retailer_cart", "finalize"]
    )
    graph.add_edge("prepare_retailer_cart", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)
