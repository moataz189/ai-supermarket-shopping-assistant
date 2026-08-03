# CP5 — FastAPI Backend & React Chat UI

Spec milestone: M1 (completes M1). Depends on: CP3, CP4.

## Goal

Expose the CP4 agent over `POST /chat` (backend-generated `thread_id`; `status` of
`success`/`partial_success`/`needs_clarification`/`awaiting_retailer_choice`;
`clarification`/`carts`/`warnings`), and build a minimal React chat UI that shows both
retailer carts side by side — completing M1.

## Scope

FastAPI schemas/route, dependency wiring, interrupt/resume translation, a minimal React SPA.
No recipe path yet (CP7), no auth, no Playwright yet (CP8).

## Deliverables

- `POST /chat` with `{"message": "..."}` starts a conversation and returns a `thread_id`.
- `status: "needs_clarification"` includes `clarification.options`; resuming with the same
  `thread_id` and the chosen option's id works.
- `status: "awaiting_retailer_choice"` includes both carts (`clarification.carts`) and three
  options (`shufersal` / `rami_levy` / `decline`); resuming with one sets `chosen_retailer`.

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
web/src/components/RetailerCartsView.tsx
```

## Files to Modify

- `app/api/main.py` — include the chat router.

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
       carts: dict | None = None  # populated only when reason == "retailer_choice"
       availability_by_retailer: dict[str, list[str]] | None = None  # only when
       # reason == "ambiguous_product" (CP4/CP7) — e.g. {"shufersal": ["Tara", "Tnuva"],
       # "rami_levy": ["President", "Tnuva"]}, so the UI can show which retailer carries
       # which option before the user picks.


   class CartLine(BaseModel):
       name: str
       item_code: str
       product_name: str
       unit_price: float
       qty: float
       subtotal: float
       link: str | None = None


   class RetailerCart(BaseModel):
       retailer: str
       items: list[CartLine]
       missing_items: list[dict]
       total: float
       budget: float | None
       over_budget_by: float | None
       trade_off_suggestions: list[dict]


   class ChatResponse(BaseModel):
       thread_id: str
       status: str
       clarification: Clarification | None = None
       carts: dict[str, RetailerCart] | None = None
       chosen_retailer: str | None = None
       warnings: list[dict] = []
   ```
2. Write `app/api/dependencies.py`:
   ```python
   from functools import lru_cache

   import os

   from app.agent.checkpointer import get_checkpointer
   from app.agent.graph import build_graph
   from app.agent.llm import get_llm
   from app.agent.mcp_clients import McpSupermarketDataClient


   @lru_cache
   def get_agent_app():
       client = McpSupermarketDataClient(
           base_url=os.environ.get("SUPERMARKET_MCP_URL", "http://localhost:8001/mcp")
       )
       return build_graph(client, get_llm(), get_checkpointer())
   ```
   `SUPERMARKET_MCP_URL` must point at CP3's server, which needs to already be running
   (`python -m mcp_servers.supermarket_mcp.server`) before the backend starts — see CP9 for
   how docker-compose brings both up together.
3. Write `app/api/routes/chat.py`, distinguishing the two interrupt reasons by status:
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
           status = "awaiting_retailer_choice" if payload["reason"] == "retailer_choice" else "needs_clarification"
           return ChatResponse(thread_id=thread_id, status=status, clarification=payload)

       final = result["final_result"]
       return ChatResponse(
           thread_id=thread_id,
           status=result["status"],
           carts=final["carts"],
           chosen_retailer=final["chosen_retailer"],
           warnings=result["warnings"],
       )
   ```
4. Modify `app/api/main.py` to include the router (unchanged pattern from CP1: `FastAPI()`,
   `app.include_router(chat_router)`, keep `/health`).
5. Write `tests/api/test_chat_endpoint.py`, overriding `get_agent_app` with a graph built
   from CP4's fakes:
   - `test_grocery_list_returns_both_carts_and_awaits_choice` — happy-path fakes; asserts
     `status == "awaiting_retailer_choice"` with both retailers present in
     `clarification.carts`; resuming with `"shufersal"` returns `chosen_retailer ==
     "shufersal"`.
   - `test_ambiguous_item_then_resumes` — fake client returns multiple merged candidates for
     one item; first call asserts `status == "needs_clarification"`; second call (same
     `thread_id`, chosen label as `message`) proceeds to the retailer-choice stage.
6. Run `pytest tests/api -v`, `ruff check`, commit backend changes.

### Frontend

7. Scaffold the React app (`npm create vite@latest web -- --template react-ts`, or write the
   files directly).
8. Write `web/src/api.ts` — a typed `ChatResponse` mirroring the backend schema and a
   `postChat(threadId, message)` fetch wrapper posting to `/api/chat`.
9. Write `web/src/components/ClarificationPrompt.tsx` — renders `question` + one button per
   `option`, calling `onSelect(option.id)`. When `availability_by_retailer` is present (item
   ambiguity, not recipe ambiguity), also render the per-retailer breakdown above the
   buttons, e.g. "Shufersal: Tara, Tnuva" / "Rami Levy: President, Tnuva", so the user can
   see what's actually available where before choosing.
10. Write `web/src/components/RetailerCartsView.tsx` — renders both carts side by side:
    per retailer, its items table, total, budget status (within/exceeds budget), savings vs.
    the other retailer, and any `trade_off_suggestions`; a choose/decline control per cart
    calling `onChoose("shufersal" | "rami_levy" | "decline")`.
11. Write `web/src/App.tsx` — holds `threadId`/`result` state; on `needs_clarification`
    render `ClarificationPrompt`; on `awaiting_retailer_choice` render `RetailerCartsView`
    from `clarification.carts` (its choose/decline calls `postChat(threadId, choice)`);
    otherwise render the final carts/warnings.
12. Wire Vite's dev-server proxy (`/api` → the FastAPI backend) so CORS isn't needed locally.
13. Start the Supermarket-Data MCP server first (`python -m mcp_servers.supermarket_mcp.server`,
    port `8001`), then `make run` (backend) and `npm run dev` (web) — the backend's real MCP
    client needs the server already listening. Manually exercise: a plain grocery list (both
    carts shown, choose one), an ambiguous query (clarification then both carts), an
    over-budget query (trade-off suggestion shown), and decline.

## Testing Tasks

- [x] `test_grocery_list_returns_both_carts_and_awaits_choice` passes.
- [x] `test_ambiguous_item_then_resumes` passes.
- [ ] Manual UI walkthrough: happy path, clarification, over-budget, decline all render
      correctly. **Partially verified, left unchecked.** All four flows (happy path,
      ambiguous-item clarification, over-budget trade-off, decline) were verified against
      the real `/chat` HTTP endpoint — wired to the real `McpSupermarketDataClient` talking
      to a live `supermarket_mcp` server over actual streamable-HTTP, through the real Vite
      dev-server proxy at `/api/chat`, with `thread_id` resume confirmed at each step (only
      the LLM was a fake, since no AWS Bedrock credentials are available in this
      environment). `npm run build` and `tsc -b` also passed, so the UI compiles cleanly
      against this exact verified contract. What's *not* verified: actually opening the
      rendered page in a browser and clicking through it — no browser-automation tool was
      available in this environment to do that visually.

## Acceptance Criteria

A user can type a plain-language grocery list and see both retailers' carts (items, totals,
budget status, savings) side by side, resolve any clarification along the way, and choose a
retailer or decline — running entirely locally.

## Risks

- LangGraph's interrupt result shape (`"__interrupt__"` key, `Interrupt` attributes) is
  version-sensitive — verify against the pinned `langgraph` version and adjust step 3 if it
  differs.
- The backend depends on the Supermarket-Data MCP server already running and reachable at
  `SUPERMARKET_MCP_URL` — if it's down, `/chat` requests fail; no local fallback/retry
  beyond the transient-error retry already in the agent's error handling.

## Notes

CP7 adds the recipe request path without changing this endpoint's contract — only the graph
behind `get_agent_app` grows a branch. CP8 extends the graph past `choose_retailer`
(Playwright, invoked only for the chosen retailer) and adds a `retailer_cart_result` field to
`ChatResponse` — that's CP8's change, not this checkpoint's.

## Definition of Done

- [x] Backend: schemas, dependencies, route implemented; both endpoint tests pass; `ruff
      check` clean.
- [ ] Frontend: chat UI built; **manual verification partial, left unchecked** — see the
      Testing Tasks note above (all four flows verified end-to-end at the HTTP/API layer the
      UI consumes, plus a clean `npm run build`; no browser was available to visually click
      through the rendered page in this environment).
- [x] Committed with message referencing CP5. **M1 milestone complete at this point.**

### Deviations from the plan

- **Bug fix in `app/agent/mcp_clients.py` (CP4 code, outside this checkpoint's declared
  "Files to Modify").** Running the real local stack (per this checkpoint's own local-run
  instructions) surfaced a real bug: `get_product_price`'s tool signature is
  `ProductPriceResponse | None`, and FastMCP wraps `Optional[BaseModel]`-typed tool results
  in a `{"result": ...}` envelope inside `structuredContent` — unlike `search_product`'s
  plain, non-optional `SearchProductResponse`, which comes back unwrapped. CP4's
  `McpSupermarketDataClient.get_product_price` returned that raw envelope directly, so every
  cart line's `unit_price`/`subtotal` lookup crashed with `KeyError: 'unit_price'` against
  a real server — invisible to CP4's fakes-only tests, since `FakeSupermarketDataClient`
  never goes through `structuredContent` unwrapping at all. Fixed by unwrapping the
  `"result"` key; re-verified against the real `supermarket_mcp` server afterward. This was
  necessary for this checkpoint's own "running entirely locally" acceptance criterion to be
  true, not optional cleanup.
- `pyproject.toml` gained a `[tool.ruff.lint.flake8-bugbear]` section with
  `extend-immutable-calls = ["fastapi.Depends"]`. Ruff's bugbear rule `B008` flags
  `Depends(...)` in a function's default arguments — which is exactly FastAPI's documented
  dependency-injection pattern, used verbatim from this plan's own `chat.py` example. This is
  the standard, documented fix (an exemption list), not a workaround.
- The Vite scaffold (`npm create vite@latest . -- --template react-ts`) now ships `oxlint`
  instead of ESLint by default; kept it as-is (`npm run lint` passes with zero findings)
  rather than swapping in a linter the plan didn't specify.
