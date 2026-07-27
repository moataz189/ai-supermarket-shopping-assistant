# CP8 — Retailer-Cart MCP Server (Playwright)

Spec milestone: M3. Depends on: CP4, CP7.

## Goal

Add the last piece of the agent's core capability: once the user chooses a retailer's cart
(CP4's `choose_retailer` interrupt — no separate approval gate needed here), open that
retailer's website via Playwright, search for and add each item/quantity to the site's
**real** cart, and stop before checkout, login, or payment — handling per-item failures and
site blocks gracefully. Automated tests run against a controlled mock retailer site; the real
Shufersal/Rami Levy sites are exercised manually only.

## Scope

A new Retailer-Cart MCP server (Playwright), a retailer-adapter abstraction (one mock
adapter for tests, two best-effort real adapters), one new LangGraph node
(`prepare_retailer_cart`), and the graph wiring to invoke it — only for the retailer the user
chose — between CP4's `choose_retailer` and `finalize`. Doesn't touch the Supermarket-Data
MCP server, ingestion, or the dietary rule engine.

## Hard Requirements (spec §1, §3, §5)

- Browser automation only runs for the retailer the user chose in CP4's `choose_retailer` —
  never automatically, never for the retailer *not* chosen.
- The automation's interface exposes **only** search/add-to-cart/cart-url actions.
  Checkout, login, and payment are not implemented anywhere in this component — by
  construction.
- A single item that can't be matched/added never aborts the run; remaining items are still
  attempted.
- A detected CAPTCHA/bot-block/login-wall stops the run gracefully with a reason and
  whatever partial result exists — never an unhandled exception.

## Deliverables

- An MCP server exposing `prepare_retailer_cart(retailer, items)`, backed by a per-retailer
  adapter and a Playwright automation loop.
- The graph invokes this server only when `chosen_retailer` is set (from CP4), scoped to
  that retailer's own cart items only.
- Automated tests against a mock retailer site: successful add, item-not-found continuation,
  graceful CAPTCHA/login-wall stopping, and a hard assertion that checkout is never reached.

## Files to Create

```
mcp_servers/retailer_cart_mcp/__init__.py
mcp_servers/retailer_cart_mcp/schemas.py
mcp_servers/retailer_cart_mcp/automation.py
mcp_servers/retailer_cart_mcp/server.py
mcp_servers/retailer_cart_mcp/adapters/__init__.py
mcp_servers/retailer_cart_mcp/adapters/shufersal.py
mcp_servers/retailer_cart_mcp/adapters/rami_levy.py
app/agent/nodes/prepare_retailer_cart.py
tests/mcp/mock_site_server.py
tests/mcp/mock_retailer_adapter.py
tests/mcp/test_retailer_cart_automation.py
tests/mcp/test_retailer_cart_mcp_contract.py
tests/agent/test_graph_retailer_choice_playwright.py
web/src/components/RetailerCartResultView.tsx
```

## Files to Modify

- `app/agent/mcp_clients.py` — add `McpRetailerCartClient`.
- `app/agent/nodes/finalize.py` — include `retailer_cart_result` in `final_result`.
- `app/agent/graph.py` — insert `prepare_retailer_cart` between `choose_retailer` and
  `finalize`, conditional on `chosen_retailer`; `build_graph` gains a `retailer_cart_client`
  parameter.
- `app/api/schemas.py` — add `RetailerCartResult`/`RetailerCartItemResult`; add
  `retailer_cart_result` to `ChatResponse` (no new status value needed — CP5's
  `awaiting_retailer_choice` already covers the interrupt).
- `app/api/routes/chat.py` — pass `retailer_cart_result` through on the final response.
- `app/api/dependencies.py` — construct `McpRetailerCartClient` and pass it to `build_graph`.
- `web/src/App.tsx` — render the real-cart result once present.
- `pyproject.toml` — add `playwright`, and as dev/test deps `pytest-playwright`, `flask`.

## Detailed Implementation Steps

### Retailer-Cart MCP server

1. Write `mcp_servers/retailer_cart_mcp/schemas.py`. There's no `product_id` in the new
   per-retailer model (CP2/CP4) — `item_code` alone identifies the item at this retailer:
   ```python
   from typing import Literal

   from pydantic import BaseModel


   class CartItemRequest(BaseModel):
       name: str
       item_code: str
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
2. Write the adapter interface and orchestration loop in
   `mcp_servers/retailer_cart_mcp/automation.py` — no checkout/login/payment method exists
   anywhere in this interface, by construction:
   ```python
   from typing import Protocol

   from playwright.async_api import Page


   class RetailerAdapter(Protocol):
       retailer_name: str

       async def open_site(self, page: Page) -> None: ...
       async def detect_block(self, page: Page) -> str | None: ...
       async def search_and_match(self, page: Page, item_name: str):
           """Navigates to search results for item_name; returns a Locator for the
           best match, or None."""
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
           # storage_state_path: optional reuse of a manually-established, out-of-band
           # login session (spec §1/§3) — the automation itself never logs in. None ⇒
           # a fresh, anonymous context.
           context = await browser.new_context(storage_state=storage_state_path)
           page = await context.new_page()
           await adapter.open_site(page)

           for index, item in enumerate(items):
               try:
                   match = await adapter.search_and_match(page, item["name"])
               except Exception as exc:
                   failed.append({"name": item["name"], "item_code": item["item_code"], "status": "error", "reason": str(exc)})
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
                   failed.append({"name": item["name"], "item_code": item["item_code"], "status": "error", "reason": str(exc)})

           if blocked_reason:
               handled = {a["name"] for a in added} | {f["name"] for f in failed}
               for remaining in items[stopped_at:]:
                   if remaining["name"] not in handled:
                       failed.append({"name": remaining["name"], "item_code": remaining["item_code"], "status": "error", "reason": "skipped_after_block"})

           cart_url = await adapter.get_cart_url(page) if not blocked_reason else None
           await browser.close()

       return {
           "retailer": adapter.retailer_name, "added": added, "failed": failed,
           "blocked": blocked_reason is not None, "blocked_reason": blocked_reason, "cart_url": cart_url,
       }
   ```
   The loop only ever calls `open_site`/`search_and_match`/`detect_block`/`add_to_cart`/
   `get_cart_url` — no path reaches checkout/login/payment, because no such method exists.
3. Write `mcp_servers/retailer_cart_mcp/adapters/shufersal.py` — best-effort, marked for
   manual verification (spec §6/§11 — not covered by CI):
   ```python
   """Best-effort adapter for shufersal.co.il. Not exercised by automated tests — verify
   selectors manually against the live site periodically. detect_block() is the safety net
   for CAPTCHA/bot-detection and site-structure drift."""

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
           return results.first if await results.count() > 0 else None

       async def add_to_cart(self, page: Page, product_locator, quantity: float) -> None:
           await product_locator.locator("button[data-testid='add-to-cart']").click()

       async def get_cart_url(self, page: Page) -> str | None:
           return f"{BASE_URL}/online/he/cart"
   ```
4. Write `mcp_servers/retailer_cart_mcp/adapters/rami_levy.py` — same structure, same
   "best-effort" docstring, `https://www.rami-levy.co.il`, its own selectors (verify
   manually — don't assume they match Shufersal's).
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
       async def prepare_retailer_cart(retailer: str, items: list[CartItemRequest]) -> PrepareRetailerCartResponse:
           result = await prepare_cart_for_retailer(adapters[retailer](), [i.model_dump() for i in items])
           return PrepareRetailerCartResponse(**result)

       return mcp


   mcp = create_server()

   if __name__ == "__main__":
       import os

       mcp.settings.host = "0.0.0.0"
       mcp.settings.port = int(os.environ.get("PORT", 8003))
       mcp.run(transport="streamable-http")
   ```
   Like CP3/CP6's servers, this runs as its own long-lived HTTP process (`PORT`, default
   `8003`) — the agent's `McpRetailerCartClient` connects over HTTP, not stdio.
6. Add `playwright`, `pytest-playwright`, `flask` to `pyproject.toml`; run `playwright
   install chromium` locally.

### Mock retailer site & automation tests

7. Write `tests/mcp/mock_site_server.py` — a small real Flask app: a search page (with
   trigger queries `TRIGGER_CAPTCHA`, `TRIGGER_LOGIN`, `no-such-item`), an add-to-cart
   action, a cart page, and a `/debug/checkout-visits` counter proving checkout is never
   reached. Add a `pytest` fixture (`tests/mcp/conftest.py`) starting it on a free port,
   yielding the base URL, resetting the counter per test.
8. Write `tests/mcp/mock_retailer_adapter.py` — `MockRetailerAdapter` implementing
   `RetailerAdapter` against the mock site's search/cart/block pages.
9. Write `tests/mcp/test_retailer_cart_automation.py` against
   `prepare_cart_for_retailer(MockRetailerAdapter(base_url), items)`:
   - successful add + correct `cart_url`.
   - one unmatched item continues with the rest (`status == "not_found"`, no exception).
   - `TRIGGER_CAPTCHA` / `TRIGGER_LOGIN` stop gracefully with the right `blocked_reason` and
     mark remaining items `"skipped_after_block"`.
   - a normal successful run, then assert `GET /debug/checkout-visits` count is `0`.
10. Write `tests/mcp/test_retailer_cart_mcp_contract.py`: `create_server({"mock_retailer":
    lambda: MockRetailerAdapter(base_url)})`, call the tool directly, assert the response
    matches `PrepareRetailerCartResponse`.
11. Run `pytest tests/mcp/test_retailer_cart_automation.py
    tests/mcp/test_retailer_cart_mcp_contract.py -v`; `ruff check`.

### LangGraph integration

12. Write `app/agent/nodes/prepare_retailer_cart.py`, reading the chosen retailer's own
    cart items out of `retailer_carts` (CP4):
    ```python
    def make_prepare_retailer_cart(retailer_cart_client):
        async def prepare_retailer_cart(state):
            retailer = state["chosen_retailer"]
            cart = state["retailer_carts"][retailer]
            items = [{"name": l["name"], "item_code": l["item_code"], "quantity": l["qty"]} for l in cart["items"]]
            result = await retailer_cart_client.prepare_retailer_cart(retailer, items)
            return {"retailer_cart_result": result}

        return prepare_retailer_cart
    ```
13. Add `McpRetailerCartClient` to `app/agent/mcp_clients.py` (same HTTP pattern as
    `McpSupermarketDataClient` — `streamablehttp_client(base_url)`, CP4 — one tool:
    `prepare_retailer_cart`), constructed with `base_url` pointed at CP8's own server
    (`RETAILER_CART_MCP_URL`, e.g. `http://localhost:8003/mcp` locally).
14. Modify `app/agent/nodes/finalize.py` to include the result if present:
    ```python
    "final_result": {
        "carts": carts,
        "chosen_retailer": state.get("chosen_retailer"),
        "retailer_cart_result": state.get("retailer_cart_result"),
    },
    ```
15. Modify `app/agent/graph.py`: `build_graph` gains a `retailer_cart_client` parameter;
    insert `prepare_retailer_cart` between `choose_retailer` and `finalize`, conditional on
    whether a retailer was chosen — this **replaces** CP4/CP7's direct
    `choose_retailer → finalize` edge:
    ```python
    def route_after_choice(state) -> str:
        return "prepare_retailer_cart" if state.get("chosen_retailer") else "finalize"


    graph.add_node("prepare_retailer_cart", make_prepare_retailer_cart(retailer_cart_client))
    graph.add_conditional_edges(
        "choose_retailer", route_after_choice, {"prepare_retailer_cart": "prepare_retailer_cart", "finalize": "finalize"}
    )
    graph.add_edge("prepare_retailer_cart", "finalize")
    ```
16. Write `tests/agent/test_graph_retailer_choice_playwright.py` with a fake
    `retailer_cart_client` (records calls, returns a canned result):
    - decline → fake client never called; `final_result["retailer_cart_result"] is None`.
    - choose `"shufersal"` → fake client called with `retailer="shufersal"` and *only*
      Shufersal's cart items (never Rami Levy's); result appears in
      `final_result["retailer_cart_result"]`.
    - fake client returns a partial result (some added, some failed) → it passes through to
      `final_result` unchanged.
17. Run the new test file; confirm CP4/CP7's existing tests still pass; `ruff check`.

### API & UI

18. Modify `app/api/schemas.py`:
    ```python
    class RetailerCartItemResult(BaseModel):
        name: str
        item_code: str
        status: str
        reason: str | None = None


    class RetailerCartResult(BaseModel):
        retailer: str
        added: list[RetailerCartItemResult]
        failed: list[RetailerCartItemResult]
        blocked: bool
        blocked_reason: str | None = None
        cart_url: str | None = None


    # ChatResponse (CP5) gains:
    #   retailer_cart_result: RetailerCartResult | None = None
    ```
19. Modify `app/api/routes/chat.py`'s final (non-interrupt) response construction to include
    `retailer_cart_result=final.get("retailer_cart_result")`. No change to interrupt
    handling — CP5's `retailer_choice` → `awaiting_retailer_choice` mapping already covers
    this checkpoint's interrupt.
20. Modify `app/api/dependencies.py`'s `get_agent_app` to construct
    `McpRetailerCartClient(base_url=os.environ.get("RETAILER_CART_MCP_URL",
    "http://localhost:8003/mcp"))` and pass it into `build_graph`.
21. Extend `tests/api/test_chat_endpoint.py` with `test_choosing_retailer_invokes_playwright`
    (fake retailer-cart client; choose `"shufersal"`; assert `retailer_cart_result` present)
    and `test_declining_skips_playwright` (assert it's absent).
22. Write `web/src/components/RetailerCartResultView.tsx` — renders `added`/`failed` items,
    a "This site blocked automation: {blocked_reason}" banner when `blocked`, a link to
    `cart_url` when present.
23. Modify `web/src/App.tsx`: once a response includes `retailer_cart_result`, render
    `RetailerCartResultView` below the (already-rendered, from CP5) chosen cart. No new
    approval UI is needed — CP5's `RetailerCartsView` choose/decline control already is the
    approval gate.
24. Manually run the full flow against the mock site: choose a retailer → see the real-cart
    result; decline → see nothing further happen.
25. Run the full test suite, `ruff check`, commit.

## Testing Tasks

- [ ] Automation-level tests (add success, not-found continuation, CAPTCHA/login-wall stop,
      never-reaches-checkout) pass against the mock site.
- [ ] MCP contract test passes.
- [ ] Graph-level tests: decline skips Playwright; choosing a retailer invokes it for *that*
      retailer's items only; partial failure passes through unchanged.
- [ ] API-level tests pass.
- [ ] CP4/CP7 regression: existing tests still pass unmodified.

## Acceptance Criteria

Once the user chooses a retailer (CP4), the agent drives that retailer's site (mock, in
tests) through search/add-to-cart for its items only, continuing past individual failures,
stopping gracefully on CAPTCHA/login-wall/bot-block, and never reaching checkout — verified
by the mock site's counter. Declining, or choosing the other retailer, never touches this
retailer's site.

## Risks

- The real adapters' selectors are best-effort until manually verified against live sites —
  expected, per spec §11; not a blocker for automated (mock-site-only) tests.
- Headless Chromium in a container needs `playwright install --with-deps` (CP9's
  Dockerfile) — local runs before CP9 need a manual `playwright install`.
- Live sites may rate-limit/block an IP under repeated testing — another reason live-site
  checks stay manual and infrequent.

## Notes

This checkpoint is the only place browser automation exists. Don't add a checkout/login/
payment method to any adapter — the guarantee is structural. The optional
`storage_state_path` (step 2) supports a manually-established login session; it's not
required for the MVP demo and isn't covered by automated tests.

## Definition of Done

- [ ] Retailer-Cart MCP server, both real adapters, mock adapter/site implemented.
- [ ] All listed tests pass; `ruff check` clean.
- [ ] Web UI shows the real-cart result once a retailer is chosen.
- [ ] Committed with message referencing CP8. **M3 milestone complete at this point.**
