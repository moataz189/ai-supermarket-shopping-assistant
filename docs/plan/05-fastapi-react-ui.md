# CP5 — FastAPI Backend & React Chat UI

Spec milestone: M1 (completes M1). Depends on: CP3, CP4.

## Goal

Expose the CP4 agent over a `POST /chat` REST endpoint matching the spec's API contract
(backend-generated `thread_id`, `status` of `success`/`partial_success`/`needs_clarification`,
`clarification`/`cart`/`warnings`), and build a minimal React chat UI that drives it —
completing the M1 milestone (local, end-to-end, direct-grocery-list-only system).

## Scope

FastAPI request/response schemas and route, dependency wiring (real MCP client + real LLM +
checkpointer from CP4), interrupt/resume translation, and a minimal React SPA. No recipe
path yet (CP7), no auth.

## Deliverables

- `POST /chat` with `{"message": "..."}` starts a new conversation and returns a `thread_id`.
- A response with `status: "needs_clarification"` includes `clarification.options`; posting
  again with the same `thread_id` and the chosen option's id as `message` resumes correctly.
- `docker-compose up` (from CP8, stubbed manually here via `make run` + `npm run dev` for
  now) serves a working chat UI end to end against local SQLite + fixture data.

## Files to Create

```
app/api/schemas.py
app/api/dependencies.py
app/api/routes/__init__.py
app/api/routes/chat.py
tests/api/test_chat_endpoint.py
web/package.json
web/vite.config.ts
web/index.html
web/src/main.tsx
web/src/App.tsx
web/src/api.ts
web/src/components/ClarificationPrompt.tsx
web/src/components/CartView.tsx
```

## Files to Modify

- `app/api/main.py` — include the new chat router.

## Detailed Implementation Steps

### Backend

1. Write `app/api/schemas.py`:
   ```python
   from pydantic import BaseModel


   class ChatRequest(BaseModel):
       thread_id: str | None = None
       message: str


   class ClarificationOption(BaseModel):
       id: str
       label: str


   class Clarification(BaseModel):
       reason: str
       question: str
       options: list[ClarificationOption]


   class CartLine(BaseModel):
       product_id: str
       item_code: str
       name: str
       retailer: str
       unit_price: float
       qty: float
       subtotal: float
       link: str | None = None


   class Cart(BaseModel):
       retailer: str | None
       items: list[CartLine]
       total: float
       budget: float | None
       over_budget_by: float | None


   class ChatResponse(BaseModel):
       thread_id: str
       status: str
       clarification: Clarification | None = None
       cart: Cart | None = None
       warnings: list[dict] = []
   ```
2. Write `app/api/dependencies.py`:
   ```python
   from functools import lru_cache

   from app.agent.checkpointer import get_checkpointer
   from app.agent.graph import build_graph
   from app.agent.llm import get_llm
   from app.agent.mcp_clients import McpSupermarketDataClient


   @lru_cache
   def get_agent_app():
       client = McpSupermarketDataClient(
           command="python", args=["-m", "mcp_servers.supermarket_mcp.server"]
       )
       return build_graph(client, get_llm(), get_checkpointer())
   ```
3. Write `app/api/routes/chat.py`:
   ```python
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
           return ChatResponse(
               thread_id=thread_id, status="needs_clarification", clarification=payload
           )

       return ChatResponse(
           thread_id=thread_id,
           status=result["status"],
           cart=result["final_cart"],
           warnings=result["warnings"],
       )
   ```
4. Modify `app/api/main.py` to include the router:
   ```python
   from fastapi import FastAPI

   from app.api.routes.chat import router as chat_router

   app = FastAPI(title="AI Supermarket Shopping Assistant")
   app.include_router(chat_router)


   @app.get("/health")
   def health() -> dict[str, str]:
       return {"status": "ok"}
   ```
5. Write `tests/api/test_chat_endpoint.py`, overriding `get_agent_app` (FastAPI dependency
   override) with a graph built from CP4's `FakeSupermarketDataClient`/`FakeLLM` via
   `build_graph`, so the test never touches a real MCP subprocess or Bedrock:
   - `test_new_conversation_returns_thread_id_and_cart` — happy-path fake data, asserts
     `status == "success"` and a `thread_id` is present.
   - `test_ambiguous_match_needs_clarification_then_resumes` — fake client configured to
     return two candidates for one item; first call asserts
     `status == "needs_clarification"` with populated `clarification.options`; second call
     reuses the returned `thread_id` and sends the chosen option's `id` as `message`, asserts
     the final response has `status in {"success", "partial_success"}` and the resolved item
     appears in `cart.items`.
6. Run `pytest tests/api -v`, iterate to green; `ruff check`; commit backend changes.

### Frontend

7. Scaffold the React app: `npm create vite@latest web -- --template react-ts` (or write
   the files directly as below if scaffolding non-interactively).
8. Write `web/src/api.ts`:
   ```typescript
   export interface ChatResponse {
     thread_id: string;
     status: "success" | "partial_success" | "needs_clarification";
     clarification: { reason: string; question: string; options: { id: string; label: string }[] } | null;
     cart: { retailer: string | null; items: any[]; total: number; budget: number | null; over_budget_by: number | null } | null;
     warnings: any[];
   }

   export async function postChat(threadId: string | null, message: string): Promise<ChatResponse> {
     const response = await fetch("/api/chat", {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       body: JSON.stringify({ thread_id: threadId, message }),
     });
     if (!response.ok) throw new Error(`Chat request failed: ${response.status}`);
     return response.json();
   }
   ```
9. Write `web/src/components/ClarificationPrompt.tsx` — renders `question` and one button
   per `option`, calling `onSelect(option.id)` on click.
10. Write `web/src/components/CartView.tsx` — renders `cart.items` as a table (name,
    retailer, unit price, qty, subtotal), `total` vs `budget`/`over_budget_by`, and the
    `warnings` list (missing items, staleness, etc.) in a visually distinct section.
11. Write `web/src/App.tsx` — holds `threadId`, `messages`, `pendingClarification`, and
    `result` in component state; a text input + send button calls `postChat`; if the
    response's `status === "needs_clarification"`, render `ClarificationPrompt` (its
    `onSelect` calls `postChat(threadId, optionId)` again); otherwise render `CartView`.
12. Wire Vite's dev server to proxy `/api` to the FastAPI backend (`vite.config.ts`
    `server.proxy`) so local development doesn't need CORS configuration.
13. Run `npm install && npm run dev` in `web/`, run the backend (`make run`) in parallel,
    and manually exercise: a plain grocery list (happy path), a query engineered to be
    ambiguous against fixture data (clarification flow), and a query with an item absent
    from fixture data (missing-item warning).

## Testing Tasks

- [ ] `test_new_conversation_returns_thread_id_and_cart` passes.
- [ ] `test_ambiguous_match_needs_clarification_then_resumes` passes.
- [ ] Manual UI walkthrough: happy path, clarification flow, missing-item flow all render
      correctly.

## Acceptance Criteria

A user can type a plain-language grocery list into the web UI and receive a rendered cart
with retailer, line items, total vs. budget, and any warnings — including a working
clarification round-trip when a product match is ambiguous — running entirely locally.

## Risks

- The exact shape of LangGraph's interrupt result (`"__interrupt__"` key and `Interrupt`
  object attributes) is version-sensitive — verify against the pinned `langgraph` version
  from CP4 and adjust the extraction in `chat.py` step 3 if it differs.
- Running the Supermarket-Data MCP server as a subprocess-per-request (via
  `McpSupermarketDataClient`) has per-call startup overhead; acceptable for MVP correctness,
  flagged as a future performance improvement (e.g. a long-lived session) rather than fixed
  now.

## Notes

CP7 will add a `/chat` request path for recipes without changing this endpoint's contract —
only the agent graph behind `get_agent_app` grows a new branch. Keep `ChatResponse` stable.
CP8 extends `ChatResponse` further (a `retailer_cart_result` field and an
`"awaiting_cart_approval"` status value) once the cart-approval + Playwright cart-preparation
step is added — that is CP8's change to make, not this checkpoint's.

## Definition of Done

- [ ] Backend: schemas, dependencies, route implemented; both endpoint tests pass; `ruff
      check` clean.
- [ ] Frontend: chat UI built and manually verified against the local backend for all three
      flows above.
- [ ] Committed with message referencing CP5. **M1 milestone complete at this point.**
