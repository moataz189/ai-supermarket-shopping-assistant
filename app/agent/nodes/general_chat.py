from app.agent.state import AgentState

_DEFAULT_REPLY = (
    "Hi! I'm your AI supermarket shopping assistant — I can help you build a grocery "
    "list, find recipes, compare Shufersal and Rami Levy prices, and manage your budget "
    "and dietary preferences. What can I help you with today?"
)


def general_chat(state: AgentState) -> AgentState:
    """Terminal node for greetings/small talk/questions about the assistant — nothing to
    shop for, so this short-circuits straight to a finalize-shaped result instead of
    running the grocery pipeline (resolve_items/build_*_cart/choose_retailer) on a message
    that was never a shopping request."""
    reply = state["parsed_request"].get("reply") or _DEFAULT_REPLY
    return {
        "status": "success",
        "warnings": [],
        "clarification": None,
        "final_result": {
            "carts": {},
            "chosen_retailer": None,
            "retailer_cart_result": None,
            "message": reply,
        },
    }
