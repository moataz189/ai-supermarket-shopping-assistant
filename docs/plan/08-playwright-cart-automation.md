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
