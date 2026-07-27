# AI Supermarket Shopping Assistant — Design

Date: 2026-07-27
Status: Approved for planning

## 1. Problem & Scope

**Problem:** Shopping across Israeli supermarket chains means manually searching each
product, comparing package sizes and prices, and repeating the process per retailer. From a
recipe, the user must also first work out the ingredients and quantities themselves.

**Proposed solution**: The system turns a natural-language request — a grocery list, or a
recipe request like "I want to make pasta" — into a shopping list, resolves each item to
what the user wants (asking only when it materially matters), and then **independently
builds the best possible complete cart for each retailer** (Shufersal Online, Rami Levy
Online) — respecting quantity, dietary restrictions, brand preference, package size,
availability, price, and an optional budget. It does **not** try to match one identical
product across retailers; it compares two independently-optimized carts and lets the user
choose one. **Item resolution works identically whether the item was typed directly (e.g.
"milk") or extracted from a recipe** (e.g. "butter, 100g") — no separate path for either.
Once the user chooses a retailer's cart, the system attempts to prepare that **real cart**
on the retailer's website via browser automation, but never proceeds to checkout, payment,
or order submission. Recipe ingredients come from a recipe API via a dedicated MCP tool.

If a retailer's site requires login, the user logs in manually beforehand — the automation
itself never logs in (see §3, Retailer-Cart MCP server).

**Hard constraint**: the system never places an order, makes a payment, or completes
checkout. Browser automation only begins after the user chooses a retailer's cart, and
stops before any checkout/login/payment step.

**Project context**: solo developer, several weeks. Course/capstone project with a fixed
technology checklist (see §9).

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
                                     ▼          ▼        │  user picks a retailer)
                   ┌──────────────────┐  ┌──────────────────────┐   ▼
                   │  Recipe MCP       │  │  Supermarket-Data MCP │  ┌───────────────────────┐
                   │  server           │  │  server                │  │  Retailer-Cart MCP     │
                   │  (wraps           │  │  (per-retailer product │  │  server (Playwright)   │
                   │   Spoonacular)    │  │   search / offer        │  │  — opens the chosen     │
                   │                   │  │   lookup)               │  │  retailer's site,       │
                   └───────────────────┘  └───────────┬────────────┘  │  searches, adds matched  │
                                                        │ queries      │  items+qty, stops before  │
                                                        ▼              │  checkout/login/payment  │
                                            ┌────────────────────────┐└───────────────────────┘
                                            │ Product DB               │
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
                                            │ (K8s CronJob deployed;    │
                                            │  manual/fixtures locally) │
                                            │ downloads Shufersal Online│
                                            │ (StoreId 413) & Rami Levy │
                                            │ Online (StoreId 39) into  │
                                            │ two independent catalogs  │
                                            └────────────────────────┘

LangGraph checkpoint/state → DynamoDB (deployed) or in-memory/SQLite (local/tests)
— enables interrupt/resume for clarification and for the final "choose a
retailer's cart" gate before browser automation runs.
```

**Division of responsibility**: the Supermarket-Data MCP server only searches/prices **one
retailer's own catalog at a time** — it never compares retailers or applies preferences.
The Retailer-Cart MCP server (Playwright) only automates the chosen retailer's site against
an already-built cart — it never searches, prices, or optimizes. All "shopping
intelligence" (resolving items, building each retailer's cart, budget/dietary/brand logic,
comparing the two carts) lives in the LangGraph agent, not in either MCP server.

**Data source**: Israeli supermarkets must publish price-transparency feeds keyed by chain,
`StoreId`, and `ItemCode`. The MVP always uses each retailer's **Online store** — Shufersal
`StoreId 413`, Rami Levy `StoreId 39` — the same store the Retailer-Cart MCP server
automates, so the priced product is the one actually added to the cart. Each retailer's feed
loads into its **own independent catalog**; there's no attempt to link "the same" product
across the two feeds (see Data Model). "Availability" means *listed in that store's feed*,
not live stock.

## 3. Components

- **LangGraph Agent** — resolves each item to what the user wants, then **independently
  builds the best cart for each retailer** (products, quantities, dietary, brand, package
  size, availability, price, budget), compares the two (totals, budget status, savings), and
  presents both for the user to choose or decline. Only after a choice does it invoke the
  Retailer-Cart MCP server, scoped to that retailer. Runs on Claude via Bedrock. State is
  persisted so a paused conversation (clarification or retailer-choice) resumes correctly.

- **Recipe MCP server** (custom) — looks up recipes and extracts ingredient name+quantity
  from Spoonacular, scaled to servings. Doesn't pick products — every ingredient feeds the
  same item-resolution step as a typed grocery item.

- **Supermarket-Data MCP server** (custom) — searches one retailer's catalog for candidates
  (a small shortlist, ~3–5) and returns pricing/listing by `ItemCode` at that retailer's
  Online `StoreId`. Never claims two retailers' items are "the same product," never applies
  preferences, never judges "best" — pure per-retailer data access.

- **Retailer-Cart MCP server (Playwright)** (custom) — after the user picks a retailer,
  opens that Online store, searches/matches/adds each cart item, and stops. No method for
  checkout/login/payment exists in this component — not just avoided at runtime. If the site
  needs auth, the user is expected to have logged in manually (an optional persisted browser
  session can be reused); absent that, a login wall is reported as `login_required` and
  automation stops gracefully. A single item that can't be matched/added is reported and
  automation continues with the rest. CAPTCHA/bot-block/unrecognized layout → stop
  gracefully, report a partial result.

- **Dietary rule engine** — deterministic (not LLM), tags products and enforces stated
  restrictions **independently within each retailer's catalog**. The LLM may propose
  substitutions but can't override a restriction. Also backs the "vegan only"/"gluten-free
  only" standing preferences (§ Product Selection).

- **Ingestion job** — downloads/validates/loads each retailer's Online-store feed into its
  own catalog on a schedule; a bad feed never replaces good data. Scheduled when deployed;
  manual/fixture-driven locally.

- **FastAPI backend** — REST API fronting the agent; issues a conversation id so
  clarification/retailer-choice interrupts resume correctly. No auth in the MVP.

- **React SPA** — chat UI plus, once both carts are built, a **side-by-side comparison**:
  per retailer, selected products, total, budget status, and savings vs. the other retailer,
  with a choose/decline control. After a choice: the real-cart result (added/failed items,
  a link if available), with warnings clearly separated.

- **Product data storage / conversation state storage** — as before: an ORM/repository
  layer over SQLite (local) / PostgreSQL (deployed); conversation state in-memory/SQLite
  (local) or DynamoDB (deployed) — only configuration changes between environments.

### Data Model (conceptual)

Products are identified **per retailer**, not by a shared cross-retailer identity: each
catalog holds its own records keyed by that retailer's `ItemCode` at its fixed `StoreId`
(Shufersal `413`, Rami Levy `39`), with name, category, package size/unit, and price. **The
MVP does not maintain a canonical cross-retailer product** — no claim that a Shufersal
`ItemCode` and a Rami Levy `ItemCode` are "the same" item. The two catalogs are stored and
queried independently.

This matches how the system actually optimizes: not "find the identical product at both
retailers," but "what's the best cart at Shufersal?" and "what's the best cart at Rami
Levy?" independently — then compare the two *results*. The same conceptual item (e.g.
"butter") may end up a different actual product at each retailer; that's expected, not a
bug, since each cart is built from what's best *within that retailer's own catalog*.

Prices are normalized to a per-unit basis (₪/kg, ₪/L) so differently-sized packages within
one retailer's catalog compare fairly — this also powers cheaper-alternative/budget-tradeoff
suggestions. Linking products across retailers (e.g. via barcode) and branch/location-aware
pricing are both future enhancements, not required for the MVP (§10).

### Product Selection & Ambiguity Resolution

Applies identically to every item, whatever its source (typed or recipe-derived).

**Resolving what the user means** (once per item, not once per retailer): the agent gathers
candidates for the item from both retailers' catalogs, merges them by name similarity into
one small shortlist (~3–5) representing the different *kinds* of product meant (brand, fat
%, flavor, dietary version) — not a cross-retailer identity claim.

**Example**:
```
Recipe ingredient: Butter, 100 grams
Matching products:
1. Tnuva butter, 200 grams
2. Tara butter, 200 grams
3. President unsalted butter, 200 grams
Agent: "Which butter would you like to use?"
```

**Rules**:
- One reasonable match → auto-select, no question.
- User already specified the exact product → don't ask again.
- Multiple equivalent products → show a small shortlist (~3–5), never exhaustive.
- Ask only when the choice materially affects product/price/package/dietary
  suitability/recipe outcome — never auto-pick a brand/package/fat%/flavor/dietary version
  when that's ambiguous and material.
- A standing preference (**cheapest**, **preferred brand**, **vegan only**, **gluten-free
  only**, or **no preference**, the default) can be set once and applied to all later
  ambiguous choices in the conversation, without re-asking.

**Applying the resolved choice per retailer**: once resolved, that choice (name/brand/
attributes) is used **separately in each retailer's own catalog** to find that retailer's
best-available match — not a shared `ItemCode` lookup. A retailer may end up with a
different actual `ItemCode`, or may not carry it at all:
- Missing at one retailer → reported for that retailer's cart only; doesn't block the other
  cart, and is never silently swapped for something unrelated.
- Any in-cart substitution (e.g. a cheaper brand for budget) is a suggestion requiring
  explicit approval, unless an automatic-substitution preference is set.

## 4. Data Flow

```
User requests a recipe or shopping list
    ↓
Extract ingredients or shopping items
    ↓
Resolve ambiguous items (merged shortlist across both retailers; ask only
when it materially matters)
    ↓
For Shufersal Online (413) and, independently, Rami Levy Online (39):
    build the best possible cart — products, quantities, dietary,
    brand, package size, availability, price, and budget
    ↓
Compare totals, budget status, and savings between the two carts
    ↓
Present both carts to the user
    ↓
User chooses which retailer's cart to proceed with (or declines)
    ↓
Retailer-Cart MCP prepares the chosen retailer's real cart
```

Notes on the less obvious parts of this flow:

- **Conversation identity**: the backend issues a conversation id on the first message; the
  client reuses it on every follow-up (clarification answers, the final retailer choice) so
  the right paused conversation resumes.
- **Recipe vs. grocery list**: a recipe request additionally looks up the recipe (asking if
  several plausible matches exist) and fetches its scaled ingredient list before item
  resolution; a direct grocery list skips straight to item resolution. Everything after that
  is identical for both.
- **Dietary substitution**: checked while each retailer's cart is built — a conflicting
  ingredient is substituted within that retailer's catalog if a suitable alternative exists,
  and only flagged if not (never silently dropped).
- **Budget as a soft constraint, per retailer**: when building each retailer's cart, the
  agent leans toward combinations that stay within budget (e.g. preferring "cheapest" ties).
  If a retailer's total still exceeds budget once the cart is built, the agent explains why
  and proposes concrete trade-offs — cheaper brand, private-label, smaller package, or, only
  as a clearly-labeled last resort, dropping a low-priority item — as **suggestions only**,
  never applied without explicit approval. Splitting one cart across both retailers to save
  money is a future enhancement, not built now — each retailer's cart stays complete and
  self-contained.
- **Presenting both carts / the approval gate**: the agent pauses once both carts are built,
  showing each retailer's products, total, budget status, and savings vs. the other, and
  asks the user to choose one or decline. This choice **is** the approval gate for browser
  automation — nothing runs against a cart the user didn't pick. Declining ends the
  interaction with both proposed carts shown and no automation.
- **After a choice**: the agent invokes the Retailer-Cart MCP server scoped to that retailer
  only. It searches/adds each item, stopping before checkout/login/payment; a single item
  that can't be matched/added is recorded as failed and automation continues with the rest.
  The final result reports what was added, what failed and why, a cart link if available,
  and — if the site blocked automation — that clearly, without failing the whole request.

## 5. Error Handling

- A failed lookup for one item never fails that retailer's cart, and never affects the
  other retailer's cart. A hard failure is reserved for the request not being able to
  continue at all (e.g. the data service is entirely unreachable, or the LLM call fails).
- Transient errors (timeouts, rate limits, temporary 5xx) are retried once; permanent ones
  (invalid input, genuinely not found) are not retried and reported immediately.
- Responses distinguish: fully successful, successful-with-warnings (still usable carts —
  e.g. over budget, an item missing at one retailer, stale data), and paused-awaiting-input.
  Warnings never block a usable cart.
- **Budget is soft, never a hard failure** — an over-budget cart is still shown, with
  trade-off suggestions, never auto-applied; the other retailer's cart is unaffected.
- Ingestion is atomic (validate-then-activate) so a bad/partial feed never corrupts existing
  data; each retailer's freshness/staleness is tracked and reported independently.
- A temporarily-unavailable live feed can fall back to a recent stored snapshot through the
  same ingestion path, so a demo isn't blocked by an external outage.
- An unintelligible request gets a clarifying question, not a guess.
- An item missing at one retailer is reported for that retailer only, never silently
  swapped for something unrelated; any substitute needs approval unless an
  automatic-substitution preference is set.
- Browser automation: a single item's failure never aborts the run (remaining items still
  attempted); a detected CAPTCHA/bot-block/login-wall/unrecognized layout stops the run
  gracefully with a reason and whatever partial result exists — never an unhandled
  exception. Automation never starts for a retailer the user didn't choose.

## 6. Testing Strategy

- **Unit**: ingredient scaling, matching/scoring, ambiguity-resolution rules (auto-select,
  respect-prior-selection, standing-preference), independent per-retailer cart building,
  budget trade-off logic, feed parsing — fixtures only, no network.
- **Integration**: API layer against a test DB and the MCP servers, using fixture responses
  (deterministic, no external dependency).
- **Contract tests**: each MCP server's I/O matches what the agent expects.
- **End-to-end agent tests**: grocery list, recipe path (incl. multiple ambiguous
  ingredients), standing preference resolving without asking, an item missing at one
  retailer only, an over-budget cart and its trade-off suggestions, dietary substitution,
  and both retailer-choice outcomes (chosen / declined).
- Dedicated tests: concurrent conversation ids never interfere; the app works against the
  production DB engine, not only the local one.
- **Ingestion tests**: bad/partial feed never corrupts existing data; staleness detection.
- **Browser-automation tests** run against a controlled mock retailer site (never the real
  sites): successful add, an unmatched item (continues with the rest), simulated
  CAPTCHA/bot-block/login-wall (stops gracefully), and a dedicated assertion that checkout/
  payment/login is never reached.
- Real-site automation is manual/best-effort only, never part of CI.
- CI runs lint + the full suite (including mock-site tests) on every change.
- Out of scope for automated tests: live recipe/retailer calls, live browser automation,
  load/performance testing.

## 7. CI/CD & Deployment

App code and Kubernetes config (dev/prod) live in one repo. Every change is linted and
tested before merge; a merge to `main` builds/publishes images and updates the dev
deployment config automatically. GitOps: an in-cluster deployment tool continuously syncs
`dev` from the repo; `prod` is only ever updated by a deliberate, reviewed, manually-synced
promotion. Terraform provisions AWS EC2; Kubernetes is self-managed (kubeadm), one cluster,
`dev`/`prod` namespaces. Prometheus/Grafana cover request latency, MCP call success/failure,
per-retailer ingestion freshness, error rates, and retailer-cart-prep success/failure/
blocked rates.

## 8. MVP & Milestones

No user accounts/auth in the MVP — all preferences (budget, dietary, brand, retailer,
standing selection preference) are inline per conversation.

- **M1 — Core agent, local only.** Direct grocery lists end-to-end: item resolution,
  independent per-retailer cart building with budget as a first-class constraint, and
  comparison/choice — minimal chat UI, local sample data.
- **M2 — Recipe path.** Recipe lookup, ingredient extraction/scaling, dietary substitution —
  feeding the same item-resolution/cart-building steps from M1.
- **M3 — Retailer cart preparation (Playwright).** Once a retailer is chosen, browser
  automation prepares its real cart, handling partial failures and blocks gracefully.
  Automated tests against a mock site; real sites verified manually.
- **M4 — Containerize & deploy to dev.** Full stack on the Kubernetes cluster; ingestion
  against live feeds on a schedule.
- **M5 — CI/CD, production, monitoring.** Build/deploy pipeline + GitOps promotion; prod and
  dashboards live.
- **M6 — Hardening & polish.** Full test suite; UI polish for clarifications, the two-cart
  comparison, real-cart results, warnings, budget trade-offs.
- **Future enhancements**: user accounts/persisted preferences, splitting one cart across
  retailers, a canonical cross-retailer product identity, branch/location-aware pricing,
  additional retailers, auto-solving CAPTCHA/bot-detection.

## 9. Requirements Traceability

| Requirement | Where addressed |
|---|---|
| Natural-language shopping requests (groceries, recipes, cleaning, personal care, etc.) | §4 |
| Search Shufersal & Rami Levy, compare price/size/availability/preferences | §3 Supermarket-Data MCP + Data Model, §4 |
| Product selection/ambiguity resolution applies uniformly to explicit items and recipe-derived ingredients | §3 Product Selection, §4 |
| Independent per-retailer cart optimization (no cross-retailer product matching required) | §2, §3 Data Model, §4 |
| Budget as a first-class, best-effort optimization constraint with approved trade-offs | §3 Product Selection, §4, §5 |
| Recipe requests via recipe API through custom MCP tool | §3 Recipe MCP server (Spoonacular) |
| Prepares the retailer's online cart but never proceeds to checkout, payment, or order submission | §1, §3 Retailer-Cart MCP server, §4, §5 |
| Real cart preparation only after the user chooses a retailer | §3, §4, §5 |
| LangGraph or LangChain agent | §2–§3 LangGraph agent |
| At least one MCP server | §3 (three: Recipe, Supermarket-Data, Retailer-Cart) |
| Custom domain-specific MCP server | §3 (all three) |
| FastAPI | §3 FastAPI backend |
| Web UI | §3 React SPA |
| Kubernetes on AWS EC2 | §7 |
| Terraform | §7 |
| Dev and prod namespaces | §7, §8 M4/M5 |
| CI/CD | §7 |
| Prometheus and Grafana | §7 |
| Unit and integration tests | §6 |

## 10. Out of Scope (MVP)

- User authentication, accounts, persisted preference profiles.
- Splitting a single cart across multiple retailers to minimize cost (MVP: one complete
  cart per retailer, user chooses between them).
- A canonical cross-retailer product identity (e.g. barcode-based linking).
- Branch/location-specific optimization beyond each retailer's fixed Online store.
- Real-time inventory guarantees (feed-based availability only).
- Checkout, login to a retailer account, or payment of any kind, at any point.
- Automatically solving/bypassing CAPTCHA or bot-detection.
- Automated tests against the real, live retailer websites.
- Load/performance testing.
- Additional retailers beyond Shufersal and Rami Levy.

## 11. Risks

- Retailer feeds could change format or go temporarily unavailable — mitigated by a
  stored-snapshot fallback and validate-before-activate ingestion.
- Each retailer's cart is optimized independently, so the same conceptual item may become a
  different actual product per retailer — intentional, but could surprise users expecting
  identical carts — mitigated by clearly labeling each cart's own selected products.
- A `StoreId` change at either retailer needs a small config update — mitigated by keeping
  `413`/`39` as named config, not hardcoded in multiple places.
- Over-asking clarification questions would feel tedious — mitigated by the auto-select/
  standing-preference rules (ask once per item, not per retailer; never re-ask once a
  preference is set).
- Budget trade-off logic could sprawl into an open-ended negotiation — mitigated by keeping
  MVP trade-offs simple (cheaper brand/private-label/smaller package, item removal only as
  a labeled last resort) and always gated on explicit approval.
- Live retailer sites may block automated browsers or change structure — mitigated by
  treating live-site automation as best-effort, stopping gracefully on any block, and never
  depending on live sites in CI.
- The full technology checklist is broad for a solo, multi-week timeline — mitigated by
  small, independently demonstrable milestones.
- Self-managed Kubernetes carries more operational risk than a managed service — mitigated
  by treating cluster setup as its own milestone.
- The LLM could misclassify a request — mitigated by keeping dietary rules, budget logic,
  and all pricing facts outside its discretion, and never letting it invoke browser
  automation without the user's explicit retailer choice.
- The recipe API's free tier may rate-limit during development/demos.

## 12. Acceptance Criteria

- A grocery-list or recipe request produces two independently-built proposed carts
  (Shufersal Online, Rami Levy Online) with matched items and totals, never placing an
  order or payment.
- **Given** a pasta request with ambiguous ingredients (butter, cream), **when** the agent
  resolves them, **then** it shows a small shortlist merged across both retailers, the user
  picks (or a standing preference applies), and the system independently builds and totals
  a cart per retailer using that choice.
- Item resolution behaves identically for typed vs. recipe-derived items, and happens once
  per item, not once per retailer.
- A standing preference (cheapest/brand/vegan only/gluten-free only) is applied instead of
  re-asking.
- **Given** a budget, **when** a retailer's best cart still exceeds it, **then** the system
  explains why and proposes trade-offs, never applying any without explicit approval.
- An item missing at one retailer is reported for that retailer only, without affecting the
  other's cart.
- Dietary constraints are enforced independently per retailer cart — substituted where
  possible, else clearly flagged, never silently included.
- Both carts are shown side by side (products, total, budget status, savings); automation
  never starts until the user chooses one; declining shows both carts with no automation.
- After a choice, the system adds matched items/quantities to that retailer's real cart,
  stopping before checkout/login/payment, and reports added/failed items (with reasons) and
  any site block, without failing the whole request.
- Runs on a self-managed Kubernetes cluster on AWS EC2 (Terraform), with dev/prod
  namespaces; `main` auto-deploys to dev, prod only via reviewed manual promotion.
- Prometheus/Grafana show latency, error rates, data freshness, and retailer-cart-prep
  outcomes.
- Unit/integration tests — including mock-site browser-automation tests — cover the core
  logic and API layer, and pass in CI.
