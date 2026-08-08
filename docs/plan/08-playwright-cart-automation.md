# CP8 — Retailer-Cart MCP Server (Playwright)

Spec milestone: M3. Depends on: CP4, CP7.

## Goal

Add the last piece of the agent's core capability: once the user chooses a retailer's cart
(CP4's `choose_retailer` interrupt — no separate approval gate needed here), open that
retailer's website via Playwright — **authenticated, using a previously-captured login
session** — and add each item/quantity to the site's **real** cart, and stop before
checkout, login, or payment — handling per-item failures and site blocks gracefully.

**Why a logged-in session is required, not optional**: a cart built anonymously is tied to
the headless browser's own throwaway cookies — once that browser closes, the user's own
browser has no way to see the same cart. Only a cart tied to a **logged-in account** persists
server-side, so the user (logged into that same account in their own browser) actually sees
what Playwright added. So this checkpoint treats a valid, previously-captured login session
as a **hard precondition** — automation refuses to even start for a retailer with no session
captured, rather than silently running anonymously and producing a cart the user can never
see. Automated tests run against a controlled mock retailer site; the real Shufersal/Rami
Levy sites are exercised manually only.

## Scope

A new Retailer-Cart MCP server (Playwright), a retailer-adapter abstraction (one mock
adapter for tests, two best-effort real adapters), a one-time manual login/session-capture
script, one new LangGraph node (`prepare_retailer_cart`), and the graph wiring to invoke it —
only for the retailer the user chose — between CP4's `choose_retailer` and `finalize`.
Doesn't touch the Supermarket-Data MCP server, ingestion, or the dietary rule engine.

## Hard Requirements (spec §1, §3, §5)

- Browser automation only runs for the retailer the user chose in CP4's `choose_retailer` —
  never automatically, never for the retailer *not* chosen.
- Browser automation only runs **using a previously-captured, logged-in session** for that
  retailer — if none exists, the tool refuses immediately with `blocked_reason:
  "login_required"` and never launches a browser. The automation itself never performs a
  login — capturing a session is always a separate, manual, out-of-band step (`login.py`,
  below), never something the automated flow does on the user's behalf.
- The automation's interface exposes **only** search/add-to-cart/cart-url actions.
  Checkout, login, and payment are not implemented anywhere in this component — by
  construction.
- A single item that can't be matched/added never aborts the run; remaining items are still
  attempted.
- A detected CAPTCHA/bot-block/login-wall stops the run gracefully with a reason and
  whatever partial result exists — never an unhandled exception.

## Deliverables

- A one-time, manual login helper (`login.py`) that opens a real, visible browser, lets the
  user log into their retailer account by hand, and saves the resulting session
  (cookies/storage) to a file the server later reuses.
- An MCP server exposing `prepare_retailer_cart(retailer, items)`, backed by a per-retailer
  adapter and a Playwright automation loop, which refuses to run for a retailer with no
  captured session.
- The graph invokes this server only when `chosen_retailer` is set (from CP4), scoped to
  that retailer's own cart items only.
- Automated tests against a mock retailer site: successful add, item-not-found continuation,
  graceful CAPTCHA/login-wall stopping, a hard assertion that checkout is never reached, and
  a contract test proving the tool refuses cleanly when no session file exists.

## Files to Create

```
mcp_servers/retailer_cart_mcp/__init__.py
mcp_servers/retailer_cart_mcp/schemas.py
mcp_servers/retailer_cart_mcp/automation.py
mcp_servers/retailer_cart_mcp/server.py
mcp_servers/retailer_cart_mcp/login.py
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
- `requirements.txt` — add `playwright` (runtime: the server itself drives a real browser).
- `requirements-dev.txt` — add `pytest-playwright` and `flask` (test-only: `flask` powers
  the mock retailer site, `tests/mcp/mock_site_server.py`, used only by tests).
- `.gitignore` — add `sessions/` (captured login sessions contain live cookies — never
  commit them).

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
           # storage_state_path reuses a session captured by login.py (manual, out-of-band
           # — the automation itself never logs in). This function stays flexible (None ⇒
           # a fresh, anonymous context) since it's a generic utility exercised directly by
           # automation-level tests against the mock site; the *product* rule that a real
           # run must always pass a valid path is enforced one layer up, in server.py's
           # `prepare_retailer_cart` tool (step 5), not here.
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
5. Write `mcp_servers/retailer_cart_mcp/server.py`. This is where the "session is required"
   rule actually lives: if `sessions/<retailer>.json` doesn't exist, the tool refuses
   immediately — no browser is ever launched — and reports every requested item as failed
   with `blocked_reason: "login_required"`:
   ```python
   import os

   from mcp.server.fastmcp import FastMCP

   from mcp_servers.retailer_cart_mcp.adapters.rami_levy import RamiLevyAdapter
   from mcp_servers.retailer_cart_mcp.adapters.shufersal import ShufersalAdapter
   from mcp_servers.retailer_cart_mcp.automation import prepare_cart_for_retailer
   from mcp_servers.retailer_cart_mcp.schemas import CartItemRequest, PrepareRetailerCartResponse

   ADAPTERS = {"shufersal": ShufersalAdapter, "rami_levy": RamiLevyAdapter}
   SESSIONS_DIR = os.environ.get("RETAILER_SESSIONS_DIR", "sessions")


   def create_server(adapters: dict = ADAPTERS, sessions_dir: str = SESSIONS_DIR) -> FastMCP:
       mcp = FastMCP("retailer-cart")

       @mcp.tool()
       async def prepare_retailer_cart(retailer: str, items: list[CartItemRequest]) -> PrepareRetailerCartResponse:
           session_path = os.path.join(sessions_dir, f"{retailer}.json")
           if not os.path.exists(session_path):
               return PrepareRetailerCartResponse(
                   retailer=retailer,
                   added=[],
                   failed=[
                       {"name": i.name, "item_code": i.item_code, "status": "error", "reason": "no_login_session"}
                       for i in items
                   ],
                   blocked=True,
                   blocked_reason="login_required",
                   cart_url=None,
               )

           result = await prepare_cart_for_retailer(
               adapters[retailer](), [i.model_dump() for i in items], storage_state_path=session_path
           )
           return PrepareRetailerCartResponse(**result)

       return mcp


   mcp = create_server()

   if __name__ == "__main__":
       mcp.settings.host = "0.0.0.0"
       mcp.settings.port = int(os.environ.get("PORT", 8003))
       mcp.run(transport="streamable-http")
   ```
   Like CP3/CP6's servers, this runs as its own long-lived HTTP process (`PORT`, default
   `8003`) — the agent's `McpRetailerCartClient` connects over HTTP, not stdio.
6. Write `mcp_servers/retailer_cart_mcp/login.py` — the **one-time, manual, out-of-band**
   session-capture helper. Run locally (never in CI, never in a container — it needs a real
   display), once per retailer, before that retailer can be used:
   ```python
   import asyncio
   import os
   import sys

   from playwright.async_api import async_playwright

   from mcp_servers.retailer_cart_mcp.adapters.rami_levy import RamiLevyAdapter
   from mcp_servers.retailer_cart_mcp.adapters.shufersal import ShufersalAdapter

   ADAPTERS = {"shufersal": ShufersalAdapter, "rami_levy": RamiLevyAdapter}
   SESSIONS_DIR = os.environ.get("RETAILER_SESSIONS_DIR", "sessions")


   async def main(retailer: str) -> None:
       adapter = ADAPTERS[retailer]()
       os.makedirs(SESSIONS_DIR, exist_ok=True)

       async with async_playwright() as p:
           browser = await p.chromium.launch(headless=False)  # visible — you log in by hand
           context = await browser.new_context()
           page = await context.new_page()
           await adapter.open_site(page)

           input(
               f"A browser window opened to {retailer}'s site. Log into your account there, "
               "then come back here and press Enter..."
           )

           session_path = os.path.join(SESSIONS_DIR, f"{retailer}.json")
           await context.storage_state(path=session_path)
           await browser.close()
           print(f"Saved {retailer} login session to {session_path}")


   if __name__ == "__main__":
       asyncio.run(main(sys.argv[1]))
   ```
   Run with `python -m mcp_servers.retailer_cart_mcp.login shufersal` (and again with
   `rami_levy`) on a machine with a real display — this produces
   `sessions/shufersal.json`/`sessions/rami_levy.json`, which step 5's `server.py` requires
   to exist before it will run automation for that retailer. These files contain live
   session cookies — never commit them (see `.gitignore`, above); getting them into a
   deployed environment is CP11/CP13's job (a Kubernetes Secret + volume mount), not this
   step's.
7. Add `playwright` to `requirements.txt`, and `pytest-playwright` + `flask` to
   `requirements-dev.txt`; run `playwright install chromium` locally.

### Mock retailer site & automation tests

8. Write `tests/mcp/mock_site_server.py` — a small real Flask app: a search page (with
   trigger queries `TRIGGER_CAPTCHA`, `TRIGGER_LOGIN`, `no-such-item`), an add-to-cart
   action, a cart page, and a `/debug/checkout-visits` counter proving checkout is never
   reached. Add a `pytest` fixture (`tests/mcp/conftest.py`) starting it on a free port,
   yielding the base URL, resetting the counter per test.
9. Write `tests/mcp/mock_retailer_adapter.py` — `MockRetailerAdapter` implementing
   `RetailerAdapter` against the mock site's search/cart/block pages.
10. Write `tests/mcp/test_retailer_cart_automation.py` against
   `prepare_cart_for_retailer(MockRetailerAdapter(base_url), items)`:
   - successful add + correct `cart_url`.
   - one unmatched item continues with the rest (`status == "not_found"`, no exception).
   - `TRIGGER_CAPTCHA` / `TRIGGER_LOGIN` stop gracefully with the right `blocked_reason` and
     mark remaining items `"skipped_after_block"`.
   - a normal successful run, then assert `GET /debug/checkout-visits` count is `0`.
11. Write `tests/mcp/test_retailer_cart_mcp_contract.py`, covering both the required-session
    check and the normal happy path:
    - `test_prepare_retailer_cart_refuses_without_session` — build
      `create_server({"mock_retailer": lambda: MockRetailerAdapter(base_url)}, sessions_dir=<empty
      tmp_path>)`; call the tool; assert `blocked is True`, `blocked_reason ==
      "login_required"`, `added == []`, and every requested item appears in `failed` with
      `reason == "no_login_session"` — and that this returns fast, without needing the mock
      site or a real browser at all (proves no browser is launched when the check fails).
    - `test_prepare_retailer_cart_succeeds_with_session_present` — same server, but
      `sessions_dir` points at a `tmp_path` containing a dummy `mock_retailer.json` file
      (any valid empty Playwright storage-state JSON, e.g. `{"cookies": [], "origins": []}`);
      call the tool for a normal successful case; assert the response matches
      `PrepareRetailerCartResponse` as before.
12. Run `pytest tests/mcp/test_retailer_cart_automation.py
    tests/mcp/test_retailer_cart_mcp_contract.py -v`; `ruff check`.

### LangGraph integration

13. Write `app/agent/nodes/prepare_retailer_cart.py`, reading the chosen retailer's own
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
14. Add `McpRetailerCartClient` to `app/agent/mcp_clients.py` (same HTTP pattern as
    `McpSupermarketDataClient` — `streamablehttp_client(base_url)`, CP4 — one tool:
    `prepare_retailer_cart`), constructed with `base_url` pointed at CP8's own server
    (`RETAILER_CART_MCP_URL`, e.g. `http://localhost:8003/mcp` locally).
15. Modify `app/agent/nodes/finalize.py` to include the result if present:
    ```python
    "final_result": {
        "carts": carts,
        "chosen_retailer": state.get("chosen_retailer"),
        "retailer_cart_result": state.get("retailer_cart_result"),
    },
    ```
16. Modify `app/agent/graph.py`: `build_graph` gains a `retailer_cart_client` parameter;
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
17. Write `tests/agent/test_graph_retailer_choice_playwright.py` with a fake
    `retailer_cart_client` (records calls, returns a canned result):
    - decline → fake client never called; `final_result["retailer_cart_result"] is None`.
    - choose `"shufersal"` → fake client called with `retailer="shufersal"` and *only*
      Shufersal's cart items (never Rami Levy's); result appears in
      `final_result["retailer_cart_result"]`.
    - fake client returns a partial result (some added, some failed) → it passes through to
      `final_result` unchanged.
18. Run the new test file; confirm CP4/CP7's existing tests still pass; `ruff check`.

### API & UI

19. Modify `app/api/schemas.py`:
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
20. Modify `app/api/routes/chat.py`'s final (non-interrupt) response construction to include
    `retailer_cart_result=final.get("retailer_cart_result")`. No change to interrupt
    handling — CP5's `retailer_choice` → `awaiting_retailer_choice` mapping already covers
    this checkpoint's interrupt.
21. Modify `app/api/dependencies.py`'s `get_agent_app` to construct
    `McpRetailerCartClient(base_url=os.environ.get("RETAILER_CART_MCP_URL",
    "http://localhost:8003/mcp"))` and pass it into `build_graph`.
22. Extend `tests/api/test_chat_endpoint.py` with `test_choosing_retailer_invokes_playwright`
    (fake retailer-cart client; choose `"shufersal"`; assert `retailer_cart_result` present)
    and `test_declining_skips_playwright` (assert it's absent).
23. Write `web/src/components/RetailerCartResultView.tsx` — renders `added`/`failed` items,
    a "This site blocked automation: {blocked_reason}" banner when `blocked`, a link to
    `cart_url` when present.
24. Modify `web/src/App.tsx`: once a response includes `retailer_cart_result`, render
    `RetailerCartResultView` below the (already-rendered, from CP5) chosen cart. No new
    approval UI is needed — CP5's `RetailerCartsView` choose/decline control already is the
    approval gate.
25. Manually run the full flow against the mock site: choose a retailer → see the real-cart
    result; decline → see nothing further happen.
26. Run the full test suite, `ruff check`, commit.

## Testing Tasks

- [ ] Automation-level tests (add success, not-found continuation, CAPTCHA/login-wall stop,
      never-reaches-checkout) pass against the mock site.
- [ ] MCP contract tests pass: refuses cleanly with no session file present (no browser
      launched); succeeds normally when a session file is present.
- [ ] Graph-level tests: decline skips Playwright; choosing a retailer invokes it for *that*
      retailer's items only; partial failure passes through unchanged.
- [ ] API-level tests pass.
- [ ] CP4/CP7 regression: existing tests still pass unmodified.

## Acceptance Criteria

Once the user chooses a retailer (CP4), the agent drives that retailer's site (mock, in
tests) through search/add-to-cart for its items only — **but only if a login session was
already captured for that retailer** (`login.py`, run manually beforehand); otherwise it
refuses immediately with `login_required`, without launching a browser. When it does run, it
continues past individual failures, stops gracefully on CAPTCHA/login-wall/bot-block, and
never reaches checkout — verified by the mock site's counter. Declining, or choosing the
other retailer, never touches this retailer's site.

## Risks

- The real adapters' selectors are best-effort until manually verified against live sites —
  expected, per spec §11; not a blocker for automated (mock-site-only) tests.
- Headless Chromium in a container needs `playwright install --with-deps` (CP9's
  Dockerfile) — local runs before CP9 need a manual `playwright install`.
- Live sites may rate-limit/block an IP under repeated testing — another reason live-site
  checks stay manual and infrequent.
- Login sessions expire (retailer-side timeout, forced logout, changed password) — a
  previously-working session file can start failing (site shows a login wall mid-run despite
  a session file existing). This surfaces as an ordinary `login_required` block via
  `detect_block`, not a crash, but the fix (re-running `login.py`) is manual; there's no
  automatic expiry detection or renewal in the MVP.
- Session files are sensitive (live login cookies) — must never be committed (`.gitignore`)
  and must be handled as securely as any other secret when moved into deployed environments
  (CP11/CP13 use a Kubernetes Secret, not a plain ConfigMap or baked-into-image file).

## Notes

This checkpoint is the only place browser automation exists. Don't add a checkout/login/
payment method to any adapter — the guarantee is structural. `storage_state_path` (step 2)
is how a captured session is reused; `login.py` (step 6) is the only place a session is ever
captured, and it is always manual and out-of-band, on a machine with a real display — never
part of the automated request-handling flow, and never run in CI or in a container.

## Definition of Done

- [ ] Retailer-Cart MCP server, both real adapters, `login.py`, mock adapter/site
      implemented.
- [ ] Server refuses to run without a captured session for the requested retailer.
- [ ] All listed tests pass; `ruff check` clean.
- [ ] Web UI shows the real-cart result once a retailer is chosen.
- [ ] Committed with message referencing CP8. **M3 milestone complete at this point.**

## CP9 follow-up — Recipe-quantity-aware carts (2026-08-08)

**The bug.** Recipe MCP (CP6) always returned real, scaled ingredient amounts (e.g.
"400 g" tomatoes, "8 ounces" spaghetti — scaled correctly for the requested servings),
and this survived correctly as far as `parsed_request["items"]`
(`get_recipe_ingredients.py` already set `quantity`/`unit` per item, confirmed by
`tests/agent/test_graph_recipe_happy_path.py`). But `build_retailer_cart.py` never read
those fields — it hardcoded `"qty": 1` for every cart line — so `prepare_retailer_cart.py`
always sent `quantity: 1` to the Retailer-Cart MCP regardless of what the recipe actually
asked for. Recipe scaling never reached the real cart at all.

**Propagation, end to end.** `build_retailer_cart.py` now also carries
`requested_quantity`/`requested_unit` (the item's real recipe amount, or `None` for an
ordinary grocery-list/weekly-shop item — those still default to the pre-existing
behavior, unchanged). `prepare_retailer_cart.py` sends this as-is to the Retailer-Cart
MCP (`CartItemRequest.quantity`/`unit`) rather than the fixed `qty`. The *retailer-specific*
conversion — normalizing a weight, rounding up to what that site actually supports,
falling back to "buy one whole package" for a weight/volume unit against a whole-unit
product — happens one layer further in, inside each adapter, using the new shared,
retailer-agnostic helpers in `mcp_servers/retailer_cart_mcp/quantity.py`
(`normalize_weight_to_kg`, `is_count_unit`, `round_up_to_increment`). `unit=None` is the
explicit signal for "no recipe data — run the exact legacy whole-unit path," so ordinary
grocery-list/weekly-shop behavior is byte-identical to before this feature existed.

**Requested quantity vs. cart quantity — kept separate, never collapsed.**
`CartItemResult`/`RetailerCartItemResult` carry `requested_quantity`/`requested_unit` (what
the recipe asked for) *and* `cart_quantity`/`cart_unit` (what the retailer's own selling
rules actually resulted in) as distinct fields — both flow unchanged through
`finalize.py`/`ChatResponse` to the frontend. `quantity_confirmed` (pre-existing field) is
kept too, for backward compatibility with the pre-existing UI code path.

**Weight normalization/rounding.** For a product sold by weight, the recipe's amount is
normalized to kg (`normalize_weight_to_kg`) and rounded *up* to the smallest retailer-
supported increment — `round_up_to_increment(requested_kg, increment_kg)` =
`ceil(requested/increment) * increment`, guarded against float precision artifacts.
Shufersal's `/cart/add` accepts an exact kg float with no rounding at all (confirmed live:
0.4 requested → 0.4 confirmed) — the increment there is effectively infinitesimal, so the
recipe's own weight is used as-is. Rami Levy's DOM stepper only moves in a fixed
per-product step with no way to represent an arbitrary weight — the adapter discovers that
step empirically from the very first click's own delta (never hardcoded to 0.5, so this
works for any weighed product, not just tomatoes) and clicks until the rounded-up target is
reached.

**Unsupported unit-to-weight conversion.** When the recipe's unit and the matched
product's retailer selling method are genuinely incompatible with no deterministic
conversion between them (a bare count against a weight-only product — e.g. "2 units" of
something sold only by kg), the adapter raises `QuantityConversionRequiredError` instead
of guessing a conversion. This surfaces as `status: "quantity_conversion_required"` with
`requested_quantity`/`requested_unit` still attached, so the failure is structured and
explainable, not a silent wrong add. The reverse case — a weight/volume unit against a
whole-unit product, e.g. "250 g pasta" — is *not* treated as an error: it buys one whole
package, the same way a person shops for packaged goods, since that's the overwhelmingly
common real case and there's no reasonable per-product package-size source to compute an
exact count from anyway.

**A second, unrelated bug found and fixed along the way**: Rami Levy's one-time
"delivery area" modal (`#delivery-modal`/`#close-popup`), which appears after a session's
very first add-to-cart click of *any* kind, was originally handled only on the weighed-item
click path. A live multi-click whole-unit add (3 clicks) hung on its 2nd click the exact
same way — the modal isn't weight-specific, so the dismiss logic
(`_click_plus_and_dismiss_first_click_modal`) is now shared by both click paths.

**Frontend.** A new `RecipeIngredientsView` component renders the scaled ingredient list
(name/quantity/unit) and is shown *before* the retailer comparison — both on the
`retailer_choice` interrupt (`choose_retailer.py` now includes `recipe` in the interrupt
payload, via a small shared `app/agent/recipe_info.py` helper also used by `finalize.py`)
and on a declined comparison view — so the user sees what a recipe actually requires
before picking a retailer, not only after. `RetailerCard` shows a recipe item's real
requested amount instead of the always-`1` comparison `qty`. `RetailerCartResultView`
shows "Recipe needs: X / Added to cart: Y" for a recipe item (both lines shown even when
they match, e.g. eggs), and a `quantity_conversion_required` failure renders as a neutral
amber "needs manual check" badge rather than a red error, since nothing was guessed wrong.

**Tests.** `tests/mcp/test_quantity.py` (pure conversion-math unit tests: weight
normalization, count-unit classification, the rounding formula, including the exact-
multiple/float-precision edge case). `tests/mcp/test_shufersal_adapter.py` and the new
`tests/mcp/test_rami_levy_adapter.py` (a minimal fake-locator harness, since this adapter
had no automated tests before — real DOM mechanics stay live-verified by hand, as before;
only the new *decision* logic is unit-tested) cover both adapters' weight/count/
incompatible-unit branches. `tests/mcp/test_retailer_cart_automation.py` covers the
orchestration-level routing (`unit=None` byte-identical to legacy, `requested_*`/`cart_*`
fields only present for recipe items, `QuantityConversionRequiredError` → structured
failure). `tests/agent/test_recipe_quantity_propagation.py` covers the full graph path
(Recipe MCP → state → cart line → Retailer-Cart MCP call → final result), scaling (4→8
servings doubling 400 g → 800 g), the interrupt-time `recipe` payload, and an explicit
no-regression check for a plain grocery-list item (`quantity: 1, unit: None`, unaffected).

**Manual verification (2026-08-08, live, via `docker compose up -d --build`).** "pasta for
4 people" → "Ratatouille Pasta" through the real web UI: the ingredient list rendered
correctly with real mixed Spoonacular units (large, servings, cloves, cups, teaspoon,
ounces) before the retailer comparison. Catalog matching for recipe items against the
Hebrew-only real product DB is a separate, pre-existing gap (recipe items search by their
English canonical name, not the localized `display_name` — same root cause as documented
in `resolve_weekly_shop_profile.py`) unrelated to this fix and out of scope here, so the
full add-to-cart round trip for a *matched* recipe item was verified directly against the
running `retailer-cart-mcp` container (real MCP call, real Hebrew item names, real sites):
Rami Levy correctly rounded a 400 g request up to a supported weight (never down) and
reported `requested_quantity=400/g` alongside a distinct `cart_quantity`/`cart_unit`;
Shufersal added the exact 0.4 kg requested with no rounding. No checkout/login/payment path
was touched, as before.

## CP9 follow-up #2 — Weekly-shop-profile quantities (2026-08-08)

**The same bug, a second source.** Following user feedback: the weekly-shop-profile
starter lists (`resolve_weekly_shop_profile.py`) had the identical "always quantity=1"
gap as recipes, just from a different origin — a single person's list and a family's list
sent the same generic amount for every item regardless of household size (e.g. tomatoes:
0.5 kg for one person is realistic, but a family needs closer to 1 kg).

Since the requested-quantity pipeline built for recipes (this same document, CP9 follow-up
#1) is entirely generic — driven by whatever `quantity`/`unit` a `parsed_request["items"]`
entry carries, regardless of source — no new plumbing was needed. `STARTER_LISTS` changed
from `dict[str, list[str]]` to `dict[str, list[dict]]`: each entry now carries a real
`quantity`/`unit` sized for that profile's household (e.g. `{"name": "עגבניה", "quantity":
0.5, "unit": "kg"}` for `one_person`, `1`/`kg` for `family`), hand-authored per profile
(kept independent per list, same as the item sets themselves — not derived via a shared
per-person multiplier). Weight/volume items (produce, meat, fish) use kg; items normally
sold as one fixed retail package (bread, milk, rice, pasta, cheese...) use a plain unit
count instead of an invented weight, for the same reason as the recipe flow's "buy one
whole package" default. A freeform/custom list (the user types their own items) is
unaffected — those still carry no quantity information at all, exactly as before.

**Tests.** `tests/agent/test_graph_weekly_shop_profile.py` gained
`test_starter_list_quantities_scale_by_household_size` (tomatoes: 0.5 kg for one_person,
1 kg for family — the user's own example) and
`test_custom_freeform_list_still_has_no_quantity_no_regression`.
`tests/agent/test_recipe_quantity_propagation.py`'s weekly-shop test was rewritten from
asserting the old "always 1/None" shape to asserting each item's real per-profile
quantity/unit reaches the Retailer-Cart MCP call.

**Manual verification (live, via rebuilt `backend`/`web` containers).** "Weekly shopping
under 250" → "Weekly family shop" through the real web UI and API: bread/milk/pasta
correctly showed "2×"/"3×"/"3× unit" (matching the authored family quantities) in both
retailers' comparison carts, and Rami Levy's cart showed "1 × kg" for tomatoes — exactly
the family quantity authored. Choosing Shufersal and running the real add-to-cart
confirmed bread/milk/pasta added at the requested counts; yellow cheese (authored as a
whole-package unit) turned out to be sold by weight on the real site and was correctly
reported as `quantity_conversion_required` instead of silently guessed — a live
confirmation that the "never guess an incompatible conversion" safety net works
correctly even when this document's own authored assumption about a product's selling
method turns out to be wrong.
