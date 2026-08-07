from uuid import uuid4

from fastapi import APIRouter, Depends
from langgraph.types import Command

from app.api.dependencies import get_agent_app
from app.api.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, agent_app=Depends(get_agent_app)) -> ChatResponse:
    is_new = request.thread_id is None
    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    if is_new:
        result = await agent_app.ainvoke({"raw_message": request.message}, config=config)
    else:
        result = await agent_app.ainvoke(Command(resume=request.message), config=config)

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
