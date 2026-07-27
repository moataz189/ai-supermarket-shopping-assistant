# AI Supermarket Shopping Assistant — Design

Date: 2026-07-27
Status: Approved for planning

## 1. Problem & Scope

**Problem:** Shopping across Israeli supermarket chains requires users to manually search
for each product, compare products, package sizes, and prices, verify whether all requested
items are available, and repeat the process across different retailers. When shopping from a
recipe, users must first identify all required ingredients, estimate the necessary
quantities, and then manually search for each ingredient on the retailer's website. This
process is time-consuming, error-prone, and makes it difficult to determine which single
retailer offers the best complete cart.

**Proposed solution**: The system converts a natural-language request — a direct grocery
list, or a recipe request such as "I want to make pasta" — into a structured shopping list,
resolves each item to a specific product (asking the user only when the choice materially
matters), retrieves matching offers from normalized supermarket price-transparency data, and
builds an optimized internal cart for the single best retailer, respecting budget, dietary,
brand, and retailer preferences. **Product resolution applies to every item in the shopping
list the same way, regardless of whether the user named it explicitly (e.g. "milk") or it
was extracted from a recipe's ingredient list (e.g. "butter, 100g" pulled from a pasta
recipe)** — there is no separate, lesser path for recipe-derived ingredients. Once the user
explicitly approves the proposed cart, the system attempts to prepare the corresponding
**real retailer cart** on the retailer's own website through browser automation — searching
for each item, matching it, and adding it with the right quantity. The system prepares the
selected retailer's online cart but never proceeds to checkout, payment, or order submission.
The agent understands requests for groceries, recipes, cleaning products, personal care, and
other supermarket items across two Israeli chains (Shufersal and Rami Levy). For recipe
requests, the agent extracts ingredients via a recipe API before searching for matching
products.

If authentication is required by the retailer's website, the user performs that login
manually, outside the automation, before browser automation begins — the automation itself
never logs in on the user's behalf (see §3, Retailer-Cart MCP server).

**Hard constraint**: the system never places an order, makes a payment, or completes
checkout. Browser automation only begins after the user explicitly approves the proposed
cart, and stops before any checkout/login/payment step.

**Project context**: solo developer, several weeks to build. This is a course/capstone final
project with a fixed checklist of required technologies (see Requirements Traceability, §9).

## 2. Architecture

```
┌─────────────┐     REST/JSON      ┌──────────────────┐
│  React SPA  │ ─────────────────▶ │  FastAPI backend │
│  (chat UI)  │ ◀───────────────── │                  │
└─────────────┘                    └────────┬─────────┘
                                             │ invokes
                                             ▼
                                  ┌───────────────────────┐
                                  │   LangGraph Agent      │
                                  │ (Claude via Amazon     │
                                  │  Bedrock Converse API) │
                                  └──┬──────────┬───────┬──┘
                         MCP calls   │          │       │ MCP call (only after
                                     ▼          ▼        │  user approves cart)
                   ┌──────────────────┐  ┌──────────────────────┐   ▼
                   │  Recipe MCP       │  │  Supermarket-Data MCP │  ┌───────────────────────┐
                   │  server           │  │  server                │  │  Retailer-Cart MCP     │
                   │  (wraps           │  │  (product search /     │  │  server (Playwright)   │
                   │   Spoonacular)    │  │   offer lookup /        │  │  — opens the retailer's │
                   │                   │  │   comparison        ) │  │  site, searches, adds   │
                   └───────────────────┘  └───────────┬────────────┘  │  matched items+qty to    │
                                                        │ queries      │  the real cart, stops    │
                                                        ▼              │  before checkout/login/  │
                                            ┌────────────────────────┐│  payment                 │
                                            │ Product DB              │└───────────────────────┘
                                            │ SQLite — local dev/tests │
                                            │ PostgreSQL — deployed    │
                                            │   dev & prod namespaces  │
                                            └────────────────────────┘
                                                        ▲
                                          validated staging load,
                                          atomic dataset activation
                                                        │
                                            ┌────────────────────────┐
                                            │ Ingestion job            │
                                            │ (K8s CronJob in deployed  │
                                            │  dev/prod; manual run     │
                                            │  against local/sample     │
                                            │  data for local dev) —    │
                                            │  downloads/parses         │
                                            │  Shufersal Online         │
                                            │  (StoreId 413) & Rami     │
                                            │  Levy Online (StoreId 39) │
                                            │  price-transparency feeds │
                                            └────────────────────────┘

LangGraph checkpoint/state → DynamoDB (deployed dev/prod namespaces) or
in-memory/SQLite (local development & automated tests) — enables
interrupt/resume for clarification questions (recipe choice, product choice)
and for the cart-approval gate before browser automation runs.
```

**Division of responsibility**: the Supermarket-Data MCP server is a data-access tool only
(search, offer lookup, comparison of specific candidates), and remains solely responsible
for feed-based product/price lookup. It does not apply preferences (e.g. "vegan only" or
"cheapest") itself — that judgment, like which candidate to use, stays in the agent layer
(see Product Selection & Ambiguity Resolution below). The Retailer-Cart MCP server (Playwright)
is responsible **only** for interacting with the retailer's live website and preparing the
real online cart — it does not search, price, or optimize anything itself; it acts strictly
on the already-optimized cart handed to it. All "shopping intelligence" — which candidate
product to use, cart optimization, applying budget/dietary/brand/retailer preferences —
lives in the LangGraph agent layer, not in either MCP server. These responsibilities are
kept deliberately separate.

**Data source**: Israeli supermarkets are legally required (Price Transparency Law) to
publish machine-readable price/product feeds, keyed by chain, store (`StoreId`), and item
(`ItemCode`). This project ingests those bulk data files rather than scraping live sites for
search/pricing, or using an unofficial API. For the MVP, ingestion and comparison always use
each retailer's **Online store**: Shufersal Online is `StoreId 413`, Rami Levy Online is
`StoreId 39` — this is also the exact branch whose website the Retailer-Cart MCP server
automates, so the product being priced/compared is the same one the automation will actually
add to the cart. Consequence: "availability" means *the item is listed in that store's
published feed*, not a live/real-time stock guarantee. The retailer website is only touched
later, and only for the narrow purpose of preparing the real cart after approval — never for
search/pricing decisions.

## 3. Components

- **LangGraph Agent** — interprets the request, orchestrates the recipe and product-search
  tools, resolves each shopping-list item (from either source) to a specific product —
  asking the user only when the choice materially matters — builds the proposed cart, pauses
  to get the user's explicit approval, and — only if approved — invokes the Retailer-Cart
  MCP server to prepare the real cart. Runs on Claude via the Amazon Bedrock Converse API.
  Conversation state is persisted so a paused (awaiting-clarification or
  awaiting-cart-approval) conversation resumes correctly rather than starting over.

- **Recipe MCP server** (custom, domain-specific) — looks up recipes and extracts their
  ingredient lists (name + quantity) from an external recipe API (Spoonacular), scaling
  quantities to the requested number of servings where supported. Every ingredient it
  returns feeds into the exact same product-resolution step as a directly-typed grocery item
  — the Recipe MCP server does not pick products itself, only ingredients.

- **Supermarket-Data MCP server** (custom, domain-specific) — searches for candidate
  products (returning a small, relevant shortlist, typically 3–5) and retrieves per-retailer
  pricing/listing information keyed by `ItemCode` at each retailer's Online store
  (`StoreId 413` / `39`). This server only retrieves data — it does not filter by preference
  or decide which single product is "best" when the choice is genuinely ambiguous. Applying
  a stated preference (cheapest, a preferred brand, vegan-only, gluten-free-only) over the
  candidates/offers this server returns, and deciding whether a choice is ambiguous enough to
  ask about, are both agent-layer responsibilities (§ Product Selection & Ambiguity
  Resolution below) — keeping this server "dumb" and consistent with its role elsewhere.

- **Retailer-Cart MCP server (Playwright)** (custom, domain-specific) — after the user
  approves the proposed cart, opens the selected retailer's **Online store** website in an
  automated browser, searches for each approved item (by its resolved `ItemCode`/name),
  matches it against the product the agent selected, adds the matched product with the
  correct quantity to the site's real shopping cart, and stops. It never logs in and never
  enters payment details — those actions are simply not implemented anywhere in this
  component, not just avoided at runtime; if the site requires authentication for cart
  actions, the user is expected to have logged in manually beforehand (e.g. via a persisted
  browser session the automation reuses) — if no valid session exists and a login wall
  appears, automation stops gracefully and reports `login_required`, exactly as it would if
  no login had ever been attempted. If an item can't be matched or added on the site,
  automation continues with the remaining items and reports the failure for that item. If
  the site presents a CAPTCHA, bot-blocking challenge, or has changed in a way the
  automation doesn't recognize, it stops gracefully and reports a partial result rather than
  failing the whole request.

- **Dietary rule engine** — a deterministic, rule-based component (not left to the
  language model's judgment) that tags products/ingredients with dietary attributes and
  enforces the user's stated dietary restrictions. The language model may propose candidate
  substitutions, but cannot override or reinterpret an explicit restriction. This engine is
  also what backs the "vegan only" / "gluten-free only" standing preferences described in
  the Product Selection section below.

- **Ingestion job** — downloads and loads the two retailers' Online-store
  price-transparency data (Shufersal `StoreId 413`, Rami Levy `StoreId 39`) on a schedule. A
  feed is fully validated before it replaces previously loaded data, so a failed or partial
  download never corrupts what's already there. Runs as a scheduled job in deployed
  environments; run manually against sample data for local development.

- **FastAPI backend** — the REST API fronting the agent. Issues a per-conversation
  identifier so multi-step interactions (like clarification questions and cart approval) can
  be resumed correctly. No user authentication in the MVP.

- **React SPA** — the chat-style web interface: request input, agent responses, inline
  product/recipe clarification prompts, the proposed cart (items, retailer, pricing, totals
  vs. budget) with an explicit approve/decline action, and — after approval — the real-cart
  preparation result (items successfully added, items that failed and why, and a link to the
  retailer's cart/site if available), with missing items and warnings clearly separated.

- **Product data storage** — holds canonical product and pricing data behind an ORM/
  repository layer, so the same application code runs against a lightweight database
  locally and a full database when deployed — only configuration changes between
  environments.

- **Conversation state storage** — persists in-progress/paused conversations so multi-turn
  interactions (e.g., waiting on a clarification answer, or waiting on cart approval) resume
  correctly; a lightweight option is used for local development and automated tests, a
  managed option when deployed.

### Data Model (conceptual)

Products are modeled at two levels: a **canonical product** (a single logical product,
matched across retailers primarily by barcode when available, with a fuzzy name/size match
as a fallback) and a **retailer offer** (that product's price and listing status at a
specific retailer's Online store). Each retailer offer is identified by that retailer's own
**`ItemCode`** (the item identifier used in its price-transparency feed) at a fixed
**`StoreId`** — Shufersal Online is `StoreId 413`, Rami Levy Online is `StoreId 39`. This
separation avoids assuming that a single product identifier is shared across retailers: the
same real-world product has a different `ItemCode` at each chain, and the canonical product
is what ties those two `ItemCode`s together as "the same thing."

"Store" in casual language means **retailer** (the chain — Shufersal or Rami Levy). For the
MVP, every price lookup and comparison uses that retailer's fixed Online `StoreId` — not an
aggregate across physical branches, and not a user-chosen branch. This is a deliberate
simplification with a concrete benefit: it's also the exact store whose website the
Retailer-Cart MCP server automates, so there's no mismatch between "the product we priced"
and "the product we'll actually try to add to the cart." Comparing or selecting among other,
physical/pickup branches — or picking a branch by the user's location — remains a future
enhancement (see §10).

Prices are normalized to a per-unit basis (e.g., per kilogram or per liter) so
differently-sized packages of the same or substitute products can be compared fairly, rather
than comparing raw shelf prices.

This feed-based data model and the optimization it powers are unaffected by browser
automation: the Retailer-Cart MCP server consumes the already-decided cart (resolved
`ItemCode`s, quantities, and the chosen retailer) — it does not re-derive pricing or
matching decisions from what it sees on the live site.

### Product Selection & Ambiguity Resolution

This applies identically to **every** item in the shopping list, whatever its source: an
item the user typed directly ("milk"), or an ingredient extracted from a recipe ("butter,
100 grams" pulled from a pasta recipe). There is no separate, simpler path for one or the
other — both go through the same search → shortlist → resolve step before anything is
priced or compared.

**Example** — the user says "I want to make pasta":

```
Recipe ingredient: Butter, 100 grams

Matching products:
1. Tnuva butter, 200 grams
2. Tara butter, 200 grams
3. President unsalted butter, 200 grams

Agent: "Which butter would you like to use?"
```

The same applies to ingredients such as pasta type, cream, cheese, tomato sauce, milk,
flour, vegetables, and meat alternatives — anywhere a recipe or a grocery-list item could
plausibly map to more than one real product.

**Rules** the agent follows when resolving an item to a product:

- If only one reasonable matching product exists, select it automatically — no question
  asked.
- If the user already specified the exact product (in this request or a prior answer in the
  same conversation), do not ask again.
- If several equivalent products exist, present a small, relevant shortlist — typically
  3–5 candidates, not an exhaustive list.
- Ask the user only when the choice can materially affect the product, price, package size,
  dietary suitability, or the recipe's outcome. The system never automatically picks a
  brand, package size, fat percentage, flavor, or dietary version on the user's behalf when
  that choice is ambiguous and material — it asks instead.
- The user may set a standing preference instead of answering every question individually:
  **cheapest matching product**, **preferred brand**, **vegan only**, **gluten-free only**,
  or **no preference** (the default). Once set, this preference is applied automatically to
  future ambiguous choices in the same conversation, without asking again for each one.

Once a product is selected — whether automatically or by the user — its **`ItemCode`**
becomes the canonical identifier for that item for the rest of the request. The system
always compares that **same `ItemCode`** across both retailers' Online stores:

- Shufersal Online — `StoreId 413`
- Rami Levy Online — `StoreId 39`

**If the selected `ItemCode` is unavailable at one retailer**:

- It is marked unavailable there — never silently swapped for a different product.
- The system may offer an alternative product, but only after informing the user that the
  originally-selected item wasn't available at that retailer.
- Any replacement product requires explicit user approval before it's used, unless the user
  has already set an automatic-substitution preference for this conversation.

## 4. Data Flow

**Main flow** (either a recipe request or a direct grocery-list request):

```
User requests a recipe or shopping list
    ↓
Extract ingredients or shopping items
    ↓
Search matching product candidates
    ↓
Resolve ambiguous ingredients
    ↓
User selects exact products or applies preferences
    ↓
Resolve ItemCode for each selected product
    ↓
Compare the same ItemCode in:
    - Shufersal Online (StoreId 413)
    - Rami Levy Online (StoreId 39)
    ↓
Calculate the complete cart total per retailer
    ↓
Present availability, item prices, and totals
    ↓
User approves the selected retailer and cart
    ↓
Retailer-Cart MCP prepares the cart
```

**Recipe request, worked example** (e.g. "shakshuka for 4 people, budget 150 shekels, no
dairy"):

1. The user sends a message. For a new conversation, the backend creates and returns a
   conversation identifier; the client includes that same identifier on every follow-up
   message (including answers to clarification questions and the cart-approval decision) so
   the correct in-progress conversation resumes rather than starting over.
2. The agent classifies the request as a recipe request and extracts the recipe, requested
   servings, budget, dietary constraints, and any retailer/brand preferences. Preferences are
   always provided inline in the request — there is no persisted user profile in the MVP.
3. The agent looks up matching recipes. If there's one clear match, it proceeds
   automatically; if several plausible recipes match, it pauses and asks the user to choose
   before going further.
4. The agent retrieves the recipe's ingredient list (name + quantity), scaled to the
   requested servings.
5. For **each** ingredient — exactly as it would for a directly-typed grocery item — the
   agent searches for candidate products and retrieves pricing/availability for a short list
   of the most likely matches, across both retailers' Online stores.
6. Dietary constraints are checked at both the recipe-selection and product-matching stages,
   using the deterministic dietary rule engine: a conflicting ingredient is first substituted
   where a suitable alternative exists, and only flagged/asked about when no substitution is
   available — it is never silently dropped.
7. If a specific ingredient has multiple plausible product matches (per the rules in §3,
   Product Selection & Ambiguity Resolution), the agent pauses and asks the user to choose —
   or applies the user's standing preference (cheapest / preferred brand / vegan only /
   gluten-free only) if one is set — then resumes from that point once answered.
8. Once every item is resolved to a specific product (and therefore a specific `ItemCode`),
   the agent builds the proposed cart using single-retailer optimization (the only mode in
   the MVP): it compares each resolved `ItemCode`'s price at Shufersal Online (`StoreId 413`)
   and Rami Levy Online (`StoreId 39`), checks whether either retailer alone can supply
   everything; if so, it picks the cheaper of those; if neither can fully cover the list, it
   picks the retailer offering the best combination of coverage and cost, and reports what's
   missing. If a resolved `ItemCode` is unavailable at one retailer, that's reported per §3's
   unavailable-`ItemCode` rules rather than silently substituted. Splitting a cart across
   multiple retailers to minimize cost is a documented future enhancement, not built now.
9. The agent presents the proposed cart (items, retailer, pricing, totals vs. budget, any
   missing items) and **pauses, asking the user to explicitly approve or decline** preparing
   this cart for real on the retailer's website. This is a distinct approval step, separate
   from the clarification interrupts in steps 3 and 7.
10. If the user declines, the conversation ends there — the proposed cart stands as the
    result, and no browser automation ever runs.
11. If the user approves, the agent invokes the Retailer-Cart MCP server with the approved
    retailer, resolved items (by `ItemCode`), and quantities. The automation opens that
    retailer's Online-store site, searches for and adds each matched item to the real cart,
    and stops before any checkout, login, or payment step. If an item can't be matched or
    added, automation continues with the rest and records that item as failed, with a
    reason.
12. The agent returns the final result: the proposed cart, and — if approved — which items
    were successfully added to the real retailer cart, which failed and why, and a link to
    the retailer's cart/site if the automation could obtain one. If the site blocked
    automation partway through (CAPTCHA, bot detection, login wall, or an unrecognized page
    layout), this is reported clearly rather than treated as a crash.
13. The web UI displays the proposed cart with its approve/decline control, any clarification
    questions inline, and — once resolved — the real-cart preparation result, with missing
    items and warnings clearly separated from successfully handled items.

**Direct grocery-list request** (e.g. "milk, bread, 2kg rice, dish soap") skips the
recipe-specific steps (3–4) — the agent extracts the item list directly from the request —
but proceeds through **exactly the same** product-selection (step 5–7), `ItemCode`
comparison (step 8), cart-approval (step 9–10), and browser-automation (steps 11–13) flow as
a recipe-derived list. Nothing about product selection differs based on where the item list
came from.

## 5. Error Handling

- A single failed lookup (e.g., one product that couldn't be checked) never fails the whole
  request — the agent continues with what it has and reports the gap. A full failure
  response is reserved for cases where the request cannot meaningfully continue at all (e.g.
  the product-data service is entirely unreachable, or the underlying language model call
  fails).
- The system distinguishes transient problems (timeouts, rate limits, temporary
  network/service errors) — which are retried once — from permanent ones (invalid input,
  genuinely not found) — which are not retried and are reported immediately.
- Responses distinguish between a fully successful result, a result with warnings (e.g., over
  budget, one item not found, one retailer's data is stale, an `ItemCode` unavailable at one
  retailer) that still contains a usable cart, and a paused result awaiting a clarification
  answer or cart-approval decision. Warnings never block returning a usable cart.
- If the total cost exceeds the stated budget, the system reports the total, the budget, and
  the amount over budget; it may suggest cheaper substitutions, but never removes items
  automatically — the user decides.
- Ingestion is atomic: a feed is fully downloaded and validated before it replaces previously
  loaded data, so a failed or partial download never corrupts what's already there.
- Each retailer's data freshness (last updated time, and whether it's considered stale) is
  tracked and reported independently — one retailer being stale doesn't hide the other's
  freshness.
- If a live retailer feed is temporarily unavailable (e.g., during a demo), a recent stored
  snapshot can be used instead, through the same ingestion process, so a temporary external
  outage doesn't block a demonstration.
- If the request itself is too vague or unintelligible to act on, the agent asks a
  clarifying question rather than guessing.
- **A selected `ItemCode` unavailable at one retailer is never silently replaced.** It's
  marked unavailable there; any alternative is only offered after telling the user, and any
  replacement requires explicit approval unless an automatic-substitution preference is set.
- **Browser automation never fails the whole request on a single item's failure.** If a
  specific item can't be found or added on the retailer's site, automation continues with
  the remaining items and that item is reported as failed, with a reason (not found on site,
  ambiguous match, add-to-cart action didn't succeed, etc.).
- **CAPTCHA, bot-blocking, login walls, or unrecognized site changes stop automation
  gracefully.** The moment any of these is detected, the automation stops taking further
  actions on the site and returns whatever partial result it already achieved (items added
  so far) along with a clear reason for stopping — this is treated as an expected, handled
  outcome, never as a crash or an unhandled exception reaching the user.
- **Approval is required before any browser automation.** The agent will not invoke the
  Retailer-Cart MCP server until the user has explicitly approved the proposed cart; a
  declined or not-yet-answered approval never triggers site automation.

## 6. Testing Strategy

- **Unit tests** cover the core logic in isolation: ingredient scaling, product
  matching/scoring, the ambiguity-resolution rules (auto-select-if-one-candidate,
  respect-prior-selection, apply-standing-preference), cart optimization, and feed parsing —
  using fixture data, no network calls.
- **Integration tests** exercise the API layer against a real test database and the MCP
  servers, using recorded fixture responses rather than live external services, so tests are
  deterministic and independent of external rate limits or downtime.
- **Contract tests** verify each MCP server's inputs/outputs match what the agent expects,
  independent of the full agent flow.
- **End-to-end agent tests** run the full request-handling flow with simulated tool
  responses, covering the key scenarios: direct grocery list, recipe path (including a
  recipe with multiple ambiguous ingredients, e.g. pasta with ambiguous butter and cream),
  ambiguous recipe/product matches requiring clarification, a standing preference resolving
  ambiguity without asking, an `ItemCode` unavailable at one retailer, missing items,
  over-budget carts, dietary substitution, cart-approval declined, and cart-approval
  approved.
- A dedicated test verifies conversations with different conversation identifiers never
  interfere with each other's state.
- A dedicated test verifies the application works correctly against the production database
  engine, not only the lightweight one used for local development.
- **Ingestion tests** verify that a failed or partial feed load never corrupts existing data,
  and that stale data is correctly detected.
- **Browser-automation tests run against a controlled mock retailer site**, not the real
  Shufersal/Rami Levy sites, covering: successful search-and-add, an item that can't be
  matched (automation continues with the rest), and simulated CAPTCHA/bot-block/login-wall
  pages (automation stops gracefully and reports why). A dedicated test asserts the
  automation never interacts with any checkout/payment/login element, even when the mock
  site's structure would make that outwardly possible.
- Automation against the real, live retailer websites is **not** part of the automated test
  suite — it is exercised manually and treated as best-effort, since CAPTCHA, bot detection,
  login requirements, and unannounced site changes are outside this project's control.
- CI runs linting and the full automated test suite (including the mock-site browser
  automation tests) on every change.
- Out of scope for automated testing: live calls to external recipe or retailer data sources,
  or live browser automation against the real retailer sites (all used only for manual/
  exploratory checks), and load/performance testing.

## 7. CI/CD & Deployment

The repository holds both application code and the Kubernetes configuration for the dev and
prod environments, organized as separate top-level directories.

On every change, automated checks (linting, tests — including mock-site browser-automation
tests) run before anything is merged. Once merged, container images are built and published,
and the deployment configuration for the dev environment is updated automatically to
reference the newly published version.

Deployment itself follows a GitOps model: a deployment tool running inside the Kubernetes
cluster continuously watches the repository and automatically applies whatever the dev
configuration says. The production environment is watched the same way, but changes there
are never applied automatically — promoting to production means deliberately updating the
production configuration (through review) and then manually triggering the deployment, so
production only changes as a result of a conscious decision.

Infrastructure (the underlying servers) is provisioned with Terraform. Kubernetes itself is
self-managed (kubeadm) on AWS EC2 rather than a managed Kubernetes service — one cluster,
with separate namespaces for dev and prod.

Prometheus and Grafana provide operational visibility: request latency, success/failure
rates of calls to the recipe and product-data services, data-ingestion success and
per-retailer freshness, error rates by category, and the success/failure/blocked rate of
retailer-cart preparation attempts.

## 8. MVP & Milestones

The MVP does not include user accounts or authentication — preferences (budget, dietary
needs, brand, retailer, and the standing product-selection preference from §3) are provided
inline with each request/conversation. Login and persisted user profiles are a planned
future enhancement, not part of the MVP.

- **M1 — Core agent, local only.** The agent handles direct grocery-list requests
  end-to-end (search, product-selection/ambiguity resolution, single-retailer cart
  optimization) with a minimal chat interface, running entirely locally against a small
  sample of product data.
- **M2 — Recipe path.** Adds the recipe lookup, ingredient extraction and scaling, and
  dietary substitution logic — feeding into the exact same product-selection step M1 already
  built, not a separate one.
- **M3 — Retailer cart preparation (Playwright).** Adds the cart-approval step and the
  Retailer-Cart MCP server: once the user approves the proposed cart, browser automation
  prepares the real cart on the retailer's Online-store site, handling partial failures and
  CAPTCHA/bot-block/login-wall situations gracefully. Automated tests run against a
  controlled mock retailer site; real-site behavior is verified manually.
- **M4 — Containerize & deploy to dev.** All services are containerized and deployed to
  the dev environment on the Kubernetes cluster; ingestion runs against the real, live
  retailer data feeds on a schedule.
- **M5 — CI/CD, production, monitoring.** The automated build/deploy pipeline and GitOps
  promotion flow are wired up; the production environment and monitoring dashboards go live.
- **M6 — Hardening & polish.** The full test suite is completed, and the interface and
  reporting (clarifications, cart approval, real-cart results, missing items, warnings,
  over-budget handling) are polished.
- **Future enhancements (explicitly out of MVP)**: user accounts and persisted preferences,
  splitting a cart across multiple retailers to minimize cost, branch/location-specific
  optimization beyond each retailer's Online store, additional retailers, automatically
  retrying/solving CAPTCHA or bot-detection challenges.

## 9. Requirements Traceability

| Requirement | Where addressed |
|---|---|
| Natural-language shopping requests (groceries, recipes, cleaning, personal care, etc.) | §4, both request paths |
| Search Shufersal & Rami Levy, compare price/size/availability/preferences | §3 Supermarket-Data MCP + Data Model, §4 steps 5–8 |
| Product selection/ambiguity resolution applies uniformly to explicit items and recipe-derived ingredients | §1, §3 Product Selection & Ambiguity Resolution, §4 steps 5–7 |
| Cross-retailer comparison by the same `ItemCode` at each retailer's Online store (`StoreId` 413 / 39) | §2, §3 Data Model, §4 step 8 |
| Recipe requests via recipe API through custom MCP tool | §3 Recipe MCP server (Spoonacular) |
| Prepares the retailer's online cart but never proceeds to checkout, payment, or order submission | §1, §3 Retailer-Cart MCP server, §4 steps 9–12, §5 |
| Real cart preparation only after explicit user approval | §3, §4 step 9–11, §5 |
| LangGraph or LangChain agent | §2–§3 LangGraph agent |
| At least one MCP server | §3 (three: Recipe MCP, Supermarket-Data MCP, Retailer-Cart MCP) |
| Custom domain-specific MCP server | §3 (all three are custom & domain-specific) |
| FastAPI | §3 FastAPI backend |
| Web UI | §3 React SPA |
| Kubernetes on AWS EC2 | §7 kubeadm cluster on Terraform-provisioned EC2 |
| Terraform | §7 |
| Dev and prod namespaces | §7, §8 M4/M5 |
| CI/CD | §7 GitHub Actions + GitOps |
| Prometheus and Grafana | §7 Monitoring |
| Unit and integration tests | §6 |

## 10. Out of Scope (MVP)

- User authentication, accounts, persisted preference profiles (planned as a future
  enhancement).
- Multi-retailer cart splitting to minimize cost.
- Branch/location-specific optimization beyond each retailer's fixed Online store (MVP
  always uses Shufersal Online `StoreId 413` and Rami Levy Online `StoreId 39`; comparing or
  selecting among other physical/pickup branches, or using the user's location to pick a
  branch, is a future enhancement).
- Real-time inventory guarantees (feed-based availability only).
- Checkout, login to a retailer account, or payment of any kind, at any point.
- Automatically solving or bypassing CAPTCHA or bot-detection challenges — the system stops
  gracefully instead.
- Automated tests against the real, live retailer websites (manual/exploratory only).
- Load/performance testing.
- Additional retailers beyond Shufersal and Rami Levy.

## 11. Risks

- The two retailers' published price/product feeds could change format, or be temporarily
  unavailable — mitigated by a stored-snapshot fallback and by validating a feed fully
  before it replaces existing data.
- Without a universal product identifier shared across retailers, matching the "same"
  product between two chains is inherently approximate — mitigated by barcode matching where
  available, a fuzzy fallback, and asking the user to clarify genuinely ambiguous matches
  rather than guessing.
- If a retailer ever changes the `StoreId` used for its Online store, ingestion/config would
  need a small update — mitigated by keeping `StoreId 413`/`39` as named configuration, not
  hardcoded inline in multiple places.
- Asking too many clarification questions could make the assistant feel tedious — mitigated
  by the auto-select/standing-preference rules in §3 (only ask when the choice materially
  matters, never re-ask once the user has stated a preference).
- **Live retailer websites may block automated browsers** (CAPTCHA, bot detection), require
  login for cart actions unexpectedly, or change their page structure and break the
  automation's selectors — mitigated by treating live-site automation as best-effort,
  stopping gracefully and reporting partial results the moment a block or unrecognized page
  is detected, and by only testing live sites manually rather than depending on them in CI.
- The full technology checklist (agent framework, three MCP servers, browser automation, API,
  web UI, self-managed Kubernetes, Terraform, CI/CD, monitoring) is broad for a solo
  developer on a multi-week timeline — mitigated by building in small, independently
  demonstrable milestones rather than all pieces at once.
- Self-managed Kubernetes (rather than a managed service) carries more operational risk
  (cluster bootstrap, networking, upgrades) — mitigated by treating cluster setup as its own
  milestone, separate from application feature work.
- The language model could misclassify a request or otherwise behave unpredictably —
  mitigated by keeping dietary-constraint enforcement and all product/pricing facts outside
  the model's discretion (a deterministic rule engine and real ingested data, never
  model-invented information), and by never letting the model itself decide to invoke
  browser automation without the user's explicit approval.
- The recipe API's free tier may have rate limits that affect availability during
  development or demonstration.

## 12. Acceptance Criteria

- A natural-language grocery-list request produces a proposed cart from a single retailer
  with matched items and total cost, without ever placing an order or making a payment.
- A recipe request produces a matching proposed cart with ingredients scaled to the
  requested number of servings, using ingredients retrieved via the recipe MCP server.
- **Given** the user asks to make pasta, **when** the recipe contains ambiguous ingredients
  such as butter and cream, **then** the system presents relevant product candidates (a
  small shortlist, not an exhaustive list), **and** the user selects the exact products (or
  applies a standing preference), **and** the system compares those selected products using
  their `ItemCode` at each retailer's Online store, **and** the system calculates the cart
  total for both online stores.
- Product selection/ambiguity resolution behaves identically whether an item came from the
  user typing it directly or from a recipe's extracted ingredient list — there is no
  request type for which ambiguous items are chosen automatically without the option to ask.
- When multiple plausible recipe or product matches exist, the system asks a clarifying
  question and correctly resumes the same conversation once answered, rather than guessing
  or starting over; when the user has set a standing preference (cheapest / brand / vegan
  only / gluten-free only), the system applies it instead of asking again.
- When an item can't be found at either retailer, the cart is still produced, with that item
  clearly reported as missing and why; when a selected `ItemCode` is unavailable at one
  retailer specifically, that's reported as such (not silently substituted), and any
  replacement requires approval unless an automatic-substitution preference is set.
- Dietary constraints stated in the request are respected: conflicting items are substituted
  where possible, or clearly flagged — never silently included.
- The system never begins browser automation on the retailer's site until the user has
  explicitly approved the proposed cart; declining ends the interaction with only the
  proposed cart shown.
- After approval, the system attempts to add the matched items and quantities to the real
  retailer cart on the retailer's Online-store website, stopping before any checkout, login,
  or payment action, and reports which items were added, which failed and why, and — if the
  site blocked automation (CAPTCHA, bot detection, login wall, unrecognized layout) — that
  this happened, without the request failing outright.
- The system runs on a self-managed Kubernetes cluster on AWS EC2, provisioned with
  Terraform, with separate dev and prod namespaces.
- Merged changes automatically reach the dev environment; production only changes through a
  deliberate, reviewed promotion step.
- Prometheus/Grafana dashboards show request latency, error rates, data freshness, and
  retailer-cart-preparation success/failure/blocked rates.
- Unit and integration tests — including browser-automation tests against a controlled mock
  retailer site — cover the core matching/optimization logic and the API layer, and pass in
  CI.
