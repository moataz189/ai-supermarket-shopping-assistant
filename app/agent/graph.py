from langgraph.graph import END, START, StateGraph

from app.agent.nodes.build_retailer_cart import make_build_retailer_cart
from app.agent.nodes.choose_retailer import choose_retailer
from app.agent.nodes.finalize import finalize
from app.agent.nodes.general_chat import general_chat
from app.agent.nodes.get_recipe_ingredients import make_get_recipe_ingredients
from app.agent.nodes.no_ingredients_to_buy import no_ingredients_to_buy
from app.agent.nodes.parse_request import make_parse_request
from app.agent.nodes.prepare_retailer_cart import make_prepare_retailer_cart
from app.agent.nodes.recipe_not_found import recipe_not_found
from app.agent.nodes.resolve_ambiguity import resolve_ambiguity, route_after_resolve
from app.agent.nodes.resolve_items import make_resolve_items
from app.agent.nodes.resolve_recipe_ambiguity import resolve_recipe_ambiguity
from app.agent.nodes.resolve_weekly_shop_profile import resolve_weekly_shop_profile
from app.agent.nodes.search_recipes import make_search_recipes, route_after_search_recipes
from app.agent.nodes.select_recipe_ingredients import (
    route_after_ingredient_selection,
    select_recipe_ingredients,
)
from app.agent.state import AgentState


def route_after_parse(state: AgentState) -> str:
    parsed = state["parsed_request"]
    request_type = parsed["request_type"]
    if request_type == "recipe":
        return "search_recipes"
    if request_type == "general_chat":
        return "general_chat"
    if request_type == "grocery_list" and not parsed["items"] and parsed.get("budget") is not None:
        return "resolve_weekly_shop_profile"
    return "resolve_items"


def route_after_choice(state: AgentState) -> str:
    return "prepare_retailer_cart" if state.get("chosen_retailer") else "finalize"


def build_graph(
    client, llm, checkpointer, recipe_client=None, retailer_cart_client=None, ingredient_dictionary=None,
):
    """`recipe_client` is optional so grocery-list-only callers (including CP4's existing
    tests) don't need to supply one — it's only ever used on the recipe branch, reached
    solely when `request_type == "recipe"`. `retailer_cart_client` is optional the same
    way — it's only ever used once the user has actually chosen a retailer (CP4).
    `ingredient_dictionary` (english_name -> hebrew_search_term) is get_recipe_ingredients'
    static Hebrew translation table (CP9 follow-up, 2026-08-08 — app/api/dependencies.py
    loads the real one once via app/agent/ingredient_dictionary.py); defaults to an empty
    dict so every ingredient is simply reported unresolved rather than crashing when a
    caller (e.g. a grocery-list-only test) has no reason to supply one."""
    graph = StateGraph(AgentState)
    graph.add_node("parse_request", make_parse_request(llm))
    graph.add_node("general_chat", general_chat)
    graph.add_node("search_recipes", make_search_recipes(recipe_client))
    graph.add_node("recipe_not_found", recipe_not_found)
    graph.add_node("resolve_recipe_ambiguity", resolve_recipe_ambiguity)
    graph.add_node(
        "get_recipe_ingredients",
        make_get_recipe_ingredients(recipe_client, ingredient_dictionary or {}),
    )
    graph.add_node("select_recipe_ingredients", select_recipe_ingredients)
    graph.add_node("no_ingredients_to_buy", no_ingredients_to_buy)
    graph.add_node("resolve_weekly_shop_profile", resolve_weekly_shop_profile)
    graph.add_node("resolve_items", make_resolve_items(client, llm))
    graph.add_node("resolve_ambiguity", resolve_ambiguity)
    graph.add_node("build_shufersal_cart", make_build_retailer_cart("shufersal", client))
    graph.add_node("build_rami_levy_cart", make_build_retailer_cart("rami_levy", client))
    graph.add_node("choose_retailer", choose_retailer)
    graph.add_node("prepare_retailer_cart", make_prepare_retailer_cart(retailer_cart_client))
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "parse_request")
    graph.add_conditional_edges(
        "parse_request",
        route_after_parse,
        ["search_recipes", "resolve_items", "general_chat", "resolve_weekly_shop_profile"],
    )
    graph.add_edge("general_chat", END)
    graph.add_edge("resolve_weekly_shop_profile", "resolve_items")
    graph.add_conditional_edges(
        "search_recipes",
        route_after_search_recipes,
        ["recipe_not_found", "resolve_recipe_ambiguity", "get_recipe_ingredients"],
    )
    graph.add_edge("recipe_not_found", END)
    graph.add_edge("resolve_recipe_ambiguity", "get_recipe_ingredients")
    graph.add_edge("get_recipe_ingredients", "select_recipe_ingredients")
    graph.add_conditional_edges(
        "select_recipe_ingredients",
        route_after_ingredient_selection,
        ["resolve_items", "no_ingredients_to_buy"],
    )
    graph.add_edge("no_ingredients_to_buy", END)
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
