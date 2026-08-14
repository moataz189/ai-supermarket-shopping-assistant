import json
import time
from uuid import uuid4

from fastapi import APIRouter, Depends
from langgraph.types import Command

from app.api.dependencies import get_agent_app
from app.api.schemas import ChatRequest, ChatResponse
from app.metrics import (
    agent_chat_request_duration_seconds,
    agent_chat_requests_total,
    cart_preparation_total,
    retailer_choice_total,
)

router = APIRouter()


def _record_cart_preparation(retailer_cart_result: dict | None) -> None:
    if retailer_cart_result is None:
        return
    if retailer_cart_result.get("blocked"):
        cart_preparation_total.labels(status="blocked").inc()
    elif retailer_cart_result.get("failed"):
        cart_preparation_total.labels(status="partial").inc()
    else:
        cart_preparation_total.labels(status="success").inc()


def _resume_value(message: str) -> str | dict | list:
    """A resume answer is normally the plain string the user typed or clicked (a
    retailer/recipe choice, free text). Two clarifications need a structured answer
    instead, so the frontend JSON-encodes it as the message string: resolve_ambiguity.py's
    per-retailer clarification (CP9 follow-up, 2026-08-08 — one choice per retailer, a
    dict) and select_recipe_ingredients.py's ingredient selection (CP10 — the selected
    ingredient ids, a list). Only treated as structured when it parses to a *dict* or
    *list* specifically; any other valid JSON (a bare number, a quoted string) is
    vanishingly unlikely free text and is passed through as the original string
    regardless, same as before this existed."""
    try:
        parsed = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return message
    return parsed if isinstance(parsed, (dict, list)) else message


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, agent_app=Depends(get_agent_app)) -> ChatResponse:
    is_new = request.thread_id is None
    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    start = time.perf_counter()
    try:
        if is_new:
            result = await agent_app.ainvoke({"raw_message": request.message}, config=config)
        else:
            result = await agent_app.ainvoke(Command(resume=_resume_value(request.message)), config=config)
    except Exception:
        agent_chat_requests_total.labels(status="error").inc()
        raise
    finally:
        agent_chat_request_duration_seconds.observe(time.perf_counter() - start)

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        reason = payload["reason"]
        is_retailer_choice = reason == "retailer_choice"
        status = "awaiting_retailer_choice" if is_retailer_choice else "needs_clarification"
        agent_chat_requests_total.labels(
            status="retailer_choice" if is_retailer_choice else "clarification"
        ).inc()
        return ChatResponse(thread_id=thread_id, status=status, clarification=payload)

    final = result["final_result"]
    agent_chat_requests_total.labels(status="success").inc()
    if final.get("chosen_retailer"):
        retailer_choice_total.labels(retailer=final["chosen_retailer"]).inc()
    _record_cart_preparation(final.get("retailer_cart_result"))

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
