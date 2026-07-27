# CP8 — Retailer-Cart MCP Server (Playwright) & Cart-Approval Gate

Spec milestone: M3. Depends on: CP4, CP7.

## Goal

Add the last piece of the agent's core capability: after the user explicitly approves the
proposed cart, open the chosen retailer's website via Playwright, search for and add each
matched item/quantity to the site's **real** shopping cart, and stop before checkout, login,
or payment — handling per-item failures and site blocks (CAPTCHA, bot detection, login wall)
gracefully. Automated tests run against a controlled mock retailer site; the real Shufersal/
Rami Levy sites are exercised manually only.

## Scope

A new Retailer-Cart MCP server (Playwright-based), a retailer-adapter abstraction (one mock
adapter for tests, two best-effort real adapters), two new LangGraph nodes (cart-approval
interrupt, cart-preparation), and the graph/API wiring changes needed to reach them. Does
not touch the Supermarket-Data MCP server, ingestion, or the dietary rule engine — those stay
exactly as CP2/CP3/CP7 left them.

## Hard Requirements (from spec §1, §3, §5)

- Browser automation **only** runs after the user explicitly approves the proposed cart —
  never automatically.
- The automation's interface exposes **only** search / add-to-cart / cart-url actions.
  Checkout, login, and payment are not implemented anywhere in this component — by
  construction, not by a runtime check.
- A single item that can't be matched or added never aborts the whole run; remaining items
  are still attempted and the failure is recorded per item.
- A detected CAPTCHA, bot-block, or login wall stops the run gracefully with a clear reason
  and whatever partial result was already achieved — never as an unhandled exception.

## Deliverables

- An MCP server exposing one tool, `prepare_retailer_cart(retailer, items)`, backed by a
  per-retailer adapter and a Playwright automation loop.
- The LangGraph agent pauses after building the proposed cart, asks for approval, and only
  invokes this MCP server if approved.
- Automated tests, run against a small local mock retailer site (not the real internet),
  covering: successful add, item-not-found continuation, graceful CAPTCHA/login-wall
  stopping, and a hard assertion that checkout is never reached.

## Files to Create

```
mcp_servers/retailer_cart_mcp/__init__.py
mcp_servers/retailer_cart_mcp/schemas.py
mcp_servers/retailer_cart_mcp/automation.py
mcp_servers/retailer_cart_mcp/server.py
mcp_servers/retailer_cart_mcp/adapters/__init__.py
mcp_servers/retailer_cart_mcp/adapters/shufersal.py
mcp_servers/retailer_cart_mcp/adapters/rami_levy.py
app/agent/nodes/await_cart_approval.py
app/agent/nodes/prepare_retailer_cart.py
tests/mcp/mock_site_server.py
tests/mcp/mock_retailer_adapter.py
tests/mcp/test_retailer_cart_automation.py
tests/mcp/test_retailer_cart_mcp_contract.py
tests/agent/test_graph_cart_approval_and_playwright.py
web/src/components/CartApprovalPrompt.tsx
web/src/components/RetailerCartResultView.tsx
```

## Files to Modify

- `app/agent/mcp_clients.py` — add `McpRetailerCartClient`.
- `app/agent/graph.py` — add `await_cart_approval`/`prepare_retailer_cart` nodes and edges
  after `finalize`; `build_graph` gains a `retailer_cart_client` parameter.
- `app/api/schemas.py` — add `RetailerCartResult`/`RetailerCartItemResult`, extend
  `ChatResponse` with `retailer_cart_result` and the `"awaiting_cart_approval"` status.
- `app/api/routes/chat.py` — distinguish the `cart_approval` interrupt reason from
  clarification reasons; pass through `retailer_cart_result`.
- `app/api/dependencies.py` — construct `McpRetailerCartClient` and pass it to `build_graph`.
- `web/src/App.tsx` — render the approval prompt and the real-cart result.
- `pyproject.toml` — add `playwright` and, as a dev/test dependency, `pytest-playwright` and
  `flask` (for the mock site).

## Detailed Implementation Steps

### Retailer-Cart MCP server

1. Write `mcp_servers/retailer_cart_mcp/schemas.py`:
   ```python
   from typing import Literal

   from pydantic import BaseModel


   class CartItemRequest(BaseModel):
       name: str
       product_id: str
       item_code: str  # the resolved product's ItemCode at this retailer (spec §3) —
                        # carried through for traceability/logging; the automation still
                        # searches the live site by name (item codes aren't a searchable
                        # field on the retailer's website), so this is not used for matching.
       quantity: float


   class CartItemResult(BaseModel):
       name: str
       item_code: str
       status: Literal["added", "not_found", "error"]
       reason: str | None = None


   class PrepareRetailerCartResponse(BaseModel):
       retailer: str
       added: list[CartItemResult]
       failed: list[CartItemResult]
       blocked: bool
       blocked_reason: str | None = None
       cart_url: str | None = None
   ```
2. Write the adapter interface as a comment-documented `Protocol` at the top of
   `mcp_servers/retailer_cart_mcp/automation.py`, followed by the orchestration loop — note
   there is deliberately no checkout/login/payment method anywhere in this interface:
   ```python
   from typing import Protocol

   from playwright.async_api import Page


   class RetailerAdapter(Protocol):
       retailer_name: str

       async def open_site(self, page: Page) -> None: ...
       async def detect_block(self, page: Page) -> str | None: ...
       async def search_and_match(self, page: Page, item_name: str):
           """Navigates to search results for item_name and returns a Locator for the
           best-matching product, or None if nothing matched."""
           ...
       async def add_to_cart(self, page: Page, product_locator, quantity: float) -> None: ...
       async def get_cart_url(self, page: Page) -> str | None: ...


   async def prepare_cart_for_retailer(
       adapter: RetailerAdapter, items: list[dict], storage_state_path: str | None = None
   ) -> dict:
       from playwright.async_api import async_playwright

       added: list[dict] = []
       failed: list[dict] = []
       blocked_reason: str | None = None
       stopped_at = len(items)

       async with async_playwright() as p:
           browser = await p.chromium.launch(headless=True)
           # storage_state_path is optional: if the user has manually logged in out of
           # band and exported a Playwright storage-state file (cookies/local storage),
           # passing it here reuses that session so cart actions on an authenticated
           # retailer site work without the automation ever performing a login itself
           # (spec §1/§3 — the automation never logs in on the user's behalf). Absent a
           # storage_state_path, this is a fresh, anonymous browser context, exactly as
           # before.
           context = await browser.new_context(storage_state=storage_state_path)
           page = await context.new_page()
           await adapter.open_site(page)

           for index, item in enumerate(items):
               try:
                   match = await adapter.search_and_match(page, item["name"])
               except Exception as exc:
                   failed.append(
                       {"name": item["name"], "item_code": item["item_code"], "status": "error", "reason": str(exc)}
                   )
                   continue

               block = await adapter.detect_block(page)
               if block:
                   blocked_reason = block
                   stopped_at = index
                   break

               if match is None:
                   failed.append({"name": item["name"], "item_code": item["item_code"], "status": "not_found"})
                   continue

               try:
                   await adapter.add_to_cart(page, match, item["quantity"])
                   added.append({"name": item["name"], "item_code": item["item_code"], "status": "added"})
               except Exception as exc:
                   failed.append(
                       {"name": item["name"], "item_code": item["item_code"], "status": "error", "reason": str(exc)}
                   )

           if blocked_reason:
               handled = {a["name"] for a in added} | {f["name"] for f in failed}
               for remaining in items[stopped_at:]:
                   if remaining["name"] not in handled:
                       failed.append(
                           {
                               "name": remaining["name"],
                               "item_code": remaining["item_code"],
                               "status": "error",
                               "reason": "skipped_after_block",
                           }
                       )

           cart_url = await adapter.get_cart_url(page) if not blocked_reason else None
           await browser.close()

       return {
           "retailer": adapter.retailer_name,
           "added": added,
           "failed": failed,
           "blocked": blocked_reason is not None,
           "blocked_reason": blocked_reason,
           "cart_url": cart_url,
       }
   ```
   Note the loop only ever calls `open_site`, `search_and_match`, `detect_block`,
   `add_to_cart`, and `get_cart_url` — there is no code path anywhere that could reach a
   checkout, login, or payment action, because no such method exists to call.
3. Write `mcp_servers/retailer_cart_mcp/adapters/shufersal.py` — a best-effort adapter,
   clearly marked as needing manual verification against the live site (spec §6/§11: live
   automation is best-effort, not covered by CI):
   ```python
   """Best-effort adapter for shufersal.co.il.

   Not exercised by automated tests (see docs/spec.md §6) — verify and adjust selectors
   manually against the live site periodically. CAPTCHA/bot-detection and site-structure
   changes are expected; detect_block() is the safety net for both.
   """

   from playwright.async_api import Page

   BASE_URL = "https://www.shufersal.co.il"


   class ShufersalAdapter:
       retailer_name = "shufersal"

       async def open_site(self, page: Page) -> None:
           await page.goto(BASE_URL)

       async def detect_block(self, page: Page) -> str | None:
           content = await page.content()
           if "px-captcha" in content or "are you human" in content.lower():
               return "captcha"
           if await page.locator("#login-password").count() > 0:
               return "login_required"
           return None

       async def search_and_match(self, page: Page, item_name: str):
           await page.goto(f"{BASE_URL}/online/he/search?text={item_name}")
           results = page.locator("[data-testid='product-tile']")
           if await results.count() == 0:
               return None
           return results.first

       async def add_to_cart(self, page: Page, product_locator, quantity: float) -> None:
           await product_locator.locator("button[data-testid='add-to-cart']").click()

       async def get_cart_url(self, page: Page) -> str | None:
           return f"{BASE_URL}/online/he/cart"
   ```
4. Write `mcp_servers/retailer_cart_mcp/adapters/rami_levy.py`, same structure and same
   "best-effort, manual verification" docstring, targeting `https://www.rami-levy.co.il`
   with its own selectors (verify manually — do not assume they match Shufersal's).
5. Write `mcp_servers/retailer_cart_mcp/server.py`:
   ```python
   from mcp.server.fastmcp import FastMCP

   from mcp_servers.retailer_cart_mcp.adapters.rami_levy import RamiLevyAdapter
   from mcp_servers.retailer_cart_mcp.adapters.shufersal import ShufersalAdapter
   from mcp_servers.retailer_cart_mcp.automation import prepare_cart_for_retailer
   from mcp_servers.retailer_cart_mcp.schemas import CartItemRequest, PrepareRetailerCartResponse

   ADAPTERS = {"shufersal": ShufersalAdapter, "rami_levy": RamiLevyAdapter}


   def create_server(adapters: dict = ADAPTERS) -> FastMCP:
       mcp = FastMCP("retailer-cart")

       @mcp.tool()
       async def prepare_retailer_cart(
           retailer: str, items: list[CartItemRequest]
       ) -> PrepareRetailerCartResponse:
           adapter = adapters[retailer]()
           result = await prepare_cart_for_retailer(
               adapter, [item.model_dump() for item in items]
           )
           return PrepareRetailerCartResponse(**result)

       return mcp


   mcp = create_server()

   if __name__ == "__main__":
       mcp.run()
   ```
6. Add `playwright`, `pytest-playwright`, and `flask` to `pyproject.toml`; run
   `playwright install chromium` locally.

### Mock retailer site & automation tests

7. Write `tests/mcp/mock_site_server.py` — a tiny real Flask app simulating a retailer site
   with a search page, an add-to-cart action, a cart page, and trigger queries for block
   scenarios, plus a debug counter used to prove checkout is never reached:
   ```python
   import threading

   from flask import Flask, jsonify, redirect, request

   _checkout_visits = {"count": 0}


   def create_app() -> Flask:
       app = Flask(__name__)
       cart: list[dict] = []

       @app.get("/search")
       def search():
           q = request.args.get("q", "")
           if q == "TRIGGER_CAPTCHA":
               return "<html><body><div id='captcha-challenge'>Verify you're human</div></body></html>"
           if q == "TRIGGER_LOGIN":
               return "<html><body><form id='login-form'><input name='password'></form></body></html>"
           if q == "no-such-item":
               return "<html><body><div id='results'></div></body></html>"
           return f"""<html><body><div id='results'>
             <div class='product' data-name='{q}'><span class='title'>{q}</span>
               <button class='add-to-cart' data-name='{q}'>Add to cart</button></div>
           </div></body></html>"""

       @app.post("/cart/add")
       def add_to_cart():
           cart.append({"name": request.form["name"], "qty": int(request.form.get("qty", 1))})
           return redirect("/cart")

       @app.get("/cart")
       def view_cart():
           items = "".join(f"<li>{i['name']} x{i['qty']}</li>" for i in cart)
           return f"<html><body><ul id='cart-items'>{items}</ul><a href='/checkout' id='checkout-link'>Checkout</a></body></html>"

       @app.get("/checkout")
       def checkout():
           _checkout_visits["count"] += 1
           return "<html><body>CHECKOUT PAGE — should never be reached by automation</body></html>"

       @app.get("/debug/checkout-visits")
       def debug_checkout_visits():
           return jsonify(_checkout_visits)

       return app


   def run_mock_site(port: int) -> threading.Thread:
       app = create_app()
       thread = threading.Thread(
           target=lambda: app.run(port=port, use_reloader=False), daemon=True
       )
       thread.start()
       return thread
   ```
   Add a `pytest` fixture (in `tests/mcp/conftest.py`) that picks a free local port, calls
   `run_mock_site(port)`, waits briefly for it to be reachable, yields
   `f"http://localhost:{port}"`, and resets `_checkout_visits["count"]` at the start of each
   test.
8. Write `tests/mcp/mock_retailer_adapter.py` implementing `RetailerAdapter` against the
   mock site:
   ```python
   from playwright.async_api import Page


   class MockRetailerAdapter:
       retailer_name = "mock_retailer"

       def __init__(self, base_url: str):
           self.base_url = base_url

       async def open_site(self, page: Page) -> None:
           await page.goto(self.base_url)

       async def detect_block(self, page: Page) -> str | None:
           if await page.locator("#captcha-challenge").count() > 0:
               return "captcha"
           if await page.locator("#login-form").count() > 0:
               return "login_required"
           return None

       async def search_and_match(self, page: Page, item_name: str):
           await page.goto(f"{self.base_url}/search?q={item_name}")
           product = page.locator(f".product[data-name='{item_name}']")
           if await product.count() == 0:
               return None
           return product.first

       async def add_to_cart(self, page: Page, product_locator, quantity: float) -> None:
           await product_locator.locator(".add-to-cart").click()

       async def get_cart_url(self, page: Page) -> str | None:
           return f"{self.base_url}/cart"
   ```
9. Write `tests/mcp/test_retailer_cart_automation.py` against
   `prepare_cart_for_retailer(MockRetailerAdapter(base_url), items)`:
   - `test_adds_matching_items_and_returns_cart_url` — two real items, assert both in
     `added`, `blocked is False`, `cart_url` ends with `/cart`.
   - `test_continues_after_item_not_found` — one real item + one `"no-such-item"`, assert
     the real one is `added` and the other is in `failed` with `status == "not_found"`, and
     the run still completes (doesn't raise).
   - `test_stops_gracefully_on_captcha_and_reports_remaining_as_skipped` — items including
     `"TRIGGER_CAPTCHA"` followed by other items; assert `blocked is True`,
     `blocked_reason == "captcha"`, and every item after the trigger is `failed` with
     `reason == "skipped_after_block"` — no exception propagates.
   - `test_stops_gracefully_on_login_wall` — same shape with `"TRIGGER_LOGIN"`, asserting
     `blocked_reason == "login_required"`.
   - `test_never_visits_checkout` — run a normal successful batch, then `httpx.get(f"{base_url}/debug/checkout-visits")` and assert `count == 0`.
10. Write `tests/mcp/test_retailer_cart_mcp_contract.py`: build the server via
    `create_server({"mock_retailer": lambda: MockRetailerAdapter(base_url)})` and call the
    `prepare_retailer_cart` tool directly, asserting the response matches
    `PrepareRetailerCartResponse`'s schema for a simple successful case.
11. Run `pytest tests/mcp/test_retailer_cart_automation.py
    tests/mcp/test_retailer_cart_mcp_contract.py -v`, iterate to green; `ruff check`.

### LangGraph integration

12. Write `app/agent/nodes/await_cart_approval.py`:
    ```python
    from langgraph.types import interrupt


    async def await_cart_approval(state):
        cart = state["final_cart"]
        answer = interrupt(
            {
                "reason": "cart_approval",
                "question": (
                    f"I've put together a cart at {cart['retailer']} totaling {cart['total']}. "
                    "Add these items to your real cart on their website?"
                ),
                "options": [
                    {"id": "approve", "label": "Yes, add to my cart on the retailer site"},
                    {"id": "decline", "label": "No, just show me this"},
                ],
            }
        )
        return {"cart_approved": answer == "approve"}


    def route_after_approval(state) -> str:
        return "prepare_retailer_cart" if state.get("cart_approved") else "end"
    ```
13. Write `app/agent/nodes/prepare_retailer_cart.py`:
    ```python
    def make_prepare_retailer_cart(retailer_cart_client):
        async def prepare_retailer_cart(state):
            cart = state["final_cart"]
            items = [
                {
                    "name": line["name"],
                    "product_id": line["product_id"],
                    "item_code": line["item_code"],
                    "quantity": line["qty"],
                }
                for line in cart["items"]
            ]
            result = await retailer_cart_client.prepare_retailer_cart(cart["retailer"], items)
            return {"retailer_cart_result": result}

        return prepare_retailer_cart
    ```
14. Add `McpRetailerCartClient` to `app/agent/mcp_clients.py`, structurally identical to
    `McpSupermarketDataClient`, targeting CP8's server and its one tool:
    ```python
    class McpRetailerCartClient:
        def __init__(self, command: str, args: list[str]):
            self._params = StdioServerParameters(command=command, args=args)

        async def _call(self, tool_name: str, arguments: dict) -> dict:
            async with stdio_client(self._params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return result.structuredContent or {}

        async def prepare_retailer_cart(self, retailer: str, items: list[dict]) -> dict:
            return await self._call("prepare_retailer_cart", {"retailer": retailer, "items": items})
    ```
15. Modify `app/agent/graph.py`: change `build_graph`'s signature to
    `build_graph(supermarket_client, recipe_client, retailer_cart_client, llm, checkpointer)`;
    replace the old `graph.add_edge("finalize", END)` with the approval gate:
    ```python
    graph.add_node("await_cart_approval", await_cart_approval)
    graph.add_node("prepare_retailer_cart", make_prepare_retailer_cart(retailer_cart_client))

    graph.add_edge("finalize", "await_cart_approval")
    graph.add_conditional_edges(
        "await_cart_approval",
        route_after_approval,
        {"prepare_retailer_cart": "prepare_retailer_cart", "end": END},
    )
    graph.add_edge("prepare_retailer_cart", END)
    ```
16. Write `tests/agent/test_graph_cart_approval_and_playwright.py` using a fake
    `retailer_cart_client` (a simple object recording calls and returning a canned result):
    - `test_decline_skips_playwright_entirely` — resume the approval interrupt with
      `"decline"`; assert the fake client's `prepare_retailer_cart` was never called and the
      graph completes with `final_cart` present and no `retailer_cart_result`.
    - `test_approve_invokes_playwright_and_reports_result` — resume with `"approve"`; assert
      the fake client was called with the expected retailer/items, and the terminal state's
      `retailer_cart_result` matches the fake's canned response.
    - `test_partial_playwright_failure_surfaces_in_final_state` — fake client returns a
      result with some `added` and some `failed` items; assert the terminal state carries
      that partial result through unchanged (the graph doesn't reinterpret or hide it).
17. Run `pytest tests/agent/test_graph_cart_approval_and_playwright.py -v`, iterate to
    green; confirm CP4/CP7's existing agent tests still pass unmodified (regression check).

### API & UI

18. Modify `app/api/schemas.py`:
    ```python
    class RetailerCartItemResult(BaseModel):
        name: str
        status: str
        reason: str | None = None


    class RetailerCartResult(BaseModel):
        retailer: str
        added: list[RetailerCartItemResult]
        failed: list[RetailerCartItemResult]
        blocked: bool
        blocked_reason: str | None = None
        cart_url: str | None = None


    class ChatResponse(BaseModel):
        thread_id: str
        status: str  # add "awaiting_cart_approval" to the existing set of values
        clarification: Clarification | None = None
        cart: Cart | None = None
        warnings: list[dict] = []
        retailer_cart_result: RetailerCartResult | None = None
    ```
19. Modify `app/api/routes/chat.py`'s interrupt handling to distinguish the approval
    interrupt from clarification interrupts, and to pass through the new result field:
    ```python
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        status = "awaiting_cart_approval" if payload["reason"] == "cart_approval" else "needs_clarification"
        return ChatResponse(thread_id=thread_id, status=status, clarification=payload)

    return ChatResponse(
        thread_id=thread_id,
        status=result["status"],
        cart=result["final_cart"],
        warnings=result["warnings"],
        retailer_cart_result=result.get("retailer_cart_result"),
    )
    ```
20. Modify `app/api/dependencies.py`'s `get_agent_app` to construct an
    `McpRetailerCartClient` (pointed at `mcp_servers.retailer_cart_mcp.server`) and pass it
    into `build_graph`.
21. Extend `tests/api/test_chat_endpoint.py` (from CP5) with
    `test_cart_approval_flow_declined` and `test_cart_approval_flow_approved`, using a fake
    `retailer_cart_client` the same way CP5's tests use fake supermarket/LLM dependencies.
22. Write `web/src/components/CartApprovalPrompt.tsx` — renders the proposed cart summary
    and two buttons ("Add to my cart" / "No thanks"), calling `onDecide("approve" |
    "decline")`.
23. Write `web/src/components/RetailerCartResultView.tsx` — renders `added`/`failed` items,
    a "This site blocked automation: {blocked_reason}" banner when `blocked`, and a link to
    `cart_url` when present.
24. Modify `web/src/App.tsx`: when `status === "awaiting_cart_approval"`, render the
    proposed cart plus `CartApprovalPrompt` (its `onDecide` calls `postChat(threadId,
    decision)`); when a response includes `retailer_cart_result`, render
    `RetailerCartResultView` alongside the cart.
25. Manually run the full flow locally against the mock site (or a local static copy) to
    confirm the UI correctly shows: proposed cart → approval prompt → (approve) → real-cart
    result, and separately → (decline) → no further action.
26. Run the full test suite for this checkpoint, `ruff check`, commit.

## Testing Tasks

- [ ] Automation-level tests (add success, not-found continuation, CAPTCHA stop, login-wall
      stop, never-reaches-checkout) all pass against the mock site.
- [ ] MCP contract test for `prepare_retailer_cart` passes.
- [ ] Graph-level tests: decline skips Playwright, approve invokes it, partial failure
      passed through — all pass with fakes only.
- [ ] API-level approval-flow tests pass.
- [ ] CP4/CP7 regression: existing agent tests still pass unmodified.

## Acceptance Criteria

Given a proposed cart, the agent pauses for explicit approval; declining never touches the
retailer site; approving drives a real (mock, in tests) retailer site through search and
add-to-cart for each item, continuing past individual failures, stopping gracefully and
reporting a clear reason on CAPTCHA/login-wall/bot-block, and never reaching checkout —
verified by an automated counter in the mock site tests.

## Risks

- The real Shufersal/Rami Levy adapters' selectors are best-effort guesses until manually
  verified against the live sites — expected to need adjustment; this is explicitly
  acknowledged in spec §11 and is not a blocker for automated tests, which run only against
  the mock site.
- Headless Chromium inside a container needs the OS dependencies installed by `playwright
  install --with-deps` (handled in CP9's Dockerfile) — running Playwright tests locally
  before CP9 requires the developer to run `playwright install` themselves.
- Live sites may rate-limit or permanently block an IP after repeated automated testing —
  another reason live-site verification stays manual and infrequent, not part of CI.

## Notes

This checkpoint is the only place browser automation exists in the system. Do not add any
method to `RetailerAdapter` (or any adapter) that could interact with checkout, login, or
payment — the safety guarantee here is structural, not a runtime flag to remember to check.

The optional `storage_state_path` parameter on `prepare_cart_for_retailer` (step 2) supports
reusing a session from a manual, out-of-band login (spec §1/§3) — it is not required for the
MVP demo (both retailers' Online-store carts are expected to work anonymously) and is not
covered by automated tests; treat it as a manual/best-effort feature, consistent with how
real-site automation is verified in this project.

## Definition of Done

- [ ] Retailer-Cart MCP server, both real adapters, and the mock adapter/site implemented.
- [ ] All listed automation, contract, graph, and API tests pass; `ruff check` clean.
- [ ] Web UI shows the approval prompt and real-cart result.
- [ ] Committed with message referencing CP8. **M3 milestone complete at this point.**
