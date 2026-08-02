from langgraph.graph import END, START, StateGraph

from app.agent.nodes.build_retailer_cart import make_build_retailer_cart
from app.agent.nodes.choose_retailer import choose_retailer
from app.agent.nodes.finalize import finalize
from app.agent.nodes.parse_request import make_parse_request
from app.agent.nodes.resolve_ambiguity import resolve_ambiguity, route_after_resolve
from app.agent.nodes.resolve_items import make_resolve_items
from app.agent.state import AgentState


def build_graph(client, llm, checkpointer):
    graph = StateGraph(AgentState)
    graph.add_node("parse_request", make_parse_request(llm))
    graph.add_node("resolve_items", make_resolve_items(client))
    graph.add_node("resolve_ambiguity", resolve_ambiguity)
    graph.add_node("build_shufersal_cart", make_build_retailer_cart("shufersal", client))
    graph.add_node("build_rami_levy_cart", make_build_retailer_cart("rami_levy", client))
    graph.add_node("choose_retailer", choose_retailer)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "parse_request")
    graph.add_edge("parse_request", "resolve_items")
    graph.add_conditional_edges(
        "resolve_items", route_after_resolve, ["resolve_ambiguity", "build_shufersal_cart"]
    )
    graph.add_edge("resolve_ambiguity", "resolve_items")
    graph.add_edge("build_shufersal_cart", "build_rami_levy_cart")
    graph.add_edge("build_rami_levy_cart", "choose_retailer")
    graph.add_edge("choose_retailer", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)
