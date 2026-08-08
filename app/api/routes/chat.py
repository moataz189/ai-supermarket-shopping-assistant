import json
from uuid import uuid4

from fastapi import APIRouter, Depends
from langgraph.types import Command

from app.api.dependencies import get_agent_app
from app.api.schemas import ChatRequest, ChatResponse

router = APIRouter()


def _resume_value(message: str) -> str | dict:
    """A resume answer is normally the plain string the user typed or clicked (a
    retailer/recipe choice, free text). resolve_ambiguity.py's per-retailer clarification
    (CP9 follow-up, 2026-08-08) is the one case that needs a structured answer — one
    choice per retailer — so the frontend JSON-encodes that as the message string instead.
    Only treated as structured when it parses to a *dict* specifically; any other valid
    JSON (a bare number, a quoted string) is vanishingly unlikely free text and is passed
    through as the original string regardless, same as before this existed."""
    try:
        parsed = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return message
    return parsed if isinstance(parsed, dict) else message


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, agent_app=Depends(get_agent_app)) -> ChatResponse:
    is_new = request.thread_id is None
    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    if is_new:
        result = await agent_app.ainvoke({"raw_message": request.message}, config=config)
    else:
        result = await agent_app.ainvoke(Command(resume=_resume_value(request.message)), config=config)

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        status = "awaiting_retailer_choice" if payload["reason"] == "retailer_choice" else "needs_clarification"
        return ChatResponse(thread_id=thread_id, status=status, clarification=payload)

    final = result["final_result"]
    return ChatResponse(
        thread_id=thread_id,
        status=result["status"],
        carts=final["carts"],
        chosen_retailer=final["chosen_retailer"],
        retailer_cart_result=final.get("retailer_cart_result"),
        warnings=result["warnings"],
        message=final.get("message"),
        recipe=final.get("recipe"),
    )
