# Frontend Redesign — Premium AI Shopping Assistant

Date: 2026-08-02

## Goal

Redesign the `web/` React frontend from a bare developer-demo UI into a polished,
SaaS-quality AI shopping assistant, inspired by ChatGPT, Perplexity, Instacart, and
modern grocery-AI UI kits (no copyrighted branding/assets copied). The backend API
(`/api/chat`, `ChatRequest`/`ChatResponse` schemas in `app/api/schemas.py`) is
unchanged — this is a frontend-only redesign.

## Constraints & decisions

- **Language/direction:** LTR/English UI only. Product names from retailer data may
  still render in Hebrew inline; no RTL layout support in this iteration.
- **Theme:** Light mode only for now. Dark mode is an intentional fast-follow, not
  in scope here.
- **Conversation model:** Full scrolling chat thread (all turns visible), not the
  current single-turn-replaces-previous behavior.
- **Hero behavior:** The hero (headline + centered input + prompt chips) collapses
  and transitions into the chat thread view on the first sent message, matching the
  ChatGPT/Perplexity homepage → chat pattern.
- **Illustrations:** Composed from `lucide-react` icons (shopping cart, apple,
  carrot, milk, etc.), not custom SVG art or stock imagery.
- **Answered clarification/retailer cards freeze in place** (selected option
  highlighted, others disabled/dimmed) rather than disappearing — they stay in the
  scrollback like a real conversation, and the user's choice is echoed as a new
  user bubble before the next assistant turn.

## Tech stack & setup

- **Tailwind CSS v4** via the official `@tailwindcss/vite` plugin (CSS-first
  config, no `tailwind.config.js`) — matches the project's already-current stack
  (React 19, Vite 8, TypeScript 6).
- **shadcn/ui**, initialized via its CLI (`new-york` style, neutral base color,
  CSS variables). Components are added on demand — not vendored wholesale — via
  `npx shadcn add <component>` as each is needed: `button`, `card`, `badge`,
  `input`, `avatar`, `skeleton`, `scroll-area`, `separator`.
- **`lucide-react`** for all icons, including the composed hero illustration.
- **`framer-motion`** for entrance/transition animations.
- A `@/*` path alias (`web/src/*`) is added to `tsconfig` and `vite.config.ts` for
  shadcn's import conventions.

Rejected alternative: hand-rolling Radix-free components styled to imitate
shadcn — more code to maintain, less idiomatic, and the request explicitly calls
for shadcn/ui.

## State model & data flow

`App.tsx` replaces its current single `result: ChatResponse | null` state with:

```ts
type Turn =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; status: 'loading'; expectsComparison: boolean }
  | { id: string; role: 'assistant'; status: 'done'; response: ChatResponse; answeredOptionId?: string }

type Phase = 'hero' | 'chat'
```

- Sending a message (from the hero input, a prompt chip, the pinned chat input bar,
  or a clarification/retailer choice) appends a `user` turn, appends a `loading`
  assistant turn, calls `postChat(threadId, text)` (unchanged from today), then
  replaces the loading turn with a `done` turn holding the raw `ChatResponse`.
- `expectsComparison` is set to `true` when the loading turn immediately follows an
  assistant turn whose `clarification.reason === 'retailer_choice'` — used to pick
  the loading UI (see Loading states below).
- The first successful send flips `phase` from `'hero'` to `'chat'`.
- `threadId` continues to come from `response.thread_id`, exactly as today
  (`app/api/routes/chat.py` generates it server-side via `uuid4()` on the first
  turn — no client-side change to that contract).
- Selecting a clarification option or a retailer choice calls a `send(turnId,
  optionId, label)` variant: it sets `answeredOptionId` on that specific turn (by
  `id`, looked up directly — not inferred from text) so its card can render
  itself frozen (selected option highlighted, others disabled), then appends a
  `label`-text user turn and a `loading` assistant turn, and calls
  `postChat(threadId, optionId)` exactly as a typed message would. This makes
  "was this card answered" an explicit, unambiguous piece of state rather than
  something reconstructed from later messages. (See Component breakdown.)

## Component breakdown

```
web/src/
  components/
    layout/NavBar.tsx
    layout/Hero.tsx
    illustrations/GroceryIllustration.tsx
    chat/ChatInput.tsx          variant: "hero" | "bar"
    chat/PromptChips.tsx
    chat/MessageThread.tsx
    chat/UserBubble.tsx
    chat/AssistantBubble.tsx
    chat/TypingIndicator.tsx
    clarification/ClarificationCard.tsx
    clarification/OptionChip.tsx
    retailers/RetailerComparison.tsx
    retailers/RetailerCard.tsx
  lib/utils.ts                  shadcn's cn() helper
  format.ts                     unchanged
  api.ts                        unchanged (types + postChat)
  App.tsx                       orchestrates phase/turns state
```

- **NavBar** — logo mark (Lucide icon in a rounded badge) + "AI Supermarket
  Assistant" wordmark. No auth/menu items in scope.
- **Hero** — headline "AI Supermarket Shopping Assistant", subheadline "Compare
  Shufersal and Rami Levy instantly using AI.", `GroceryIllustration`, a
  hero-variant `ChatInput`, and `PromptChips` with the four example prompts from
  the request (Pasta for 4 people / Weekly shopping under ₪250 / Gluten-free
  breakfast / Chicken, rice and vegetables). Clicking a chip fills and immediately
  sends.
- **MessageThread** — scrollable list (shadcn `ScrollArea`) that renders each
  `Turn`: `UserBubble` for `role: 'user'`; for assistant turns, `TypingIndicator`
  while `status: 'loading'`, else `AssistantBubble`, which inspects
  `response.status`/`response.clarification` to decide whether to render plain
  text, a `ClarificationCard`, or a `RetailerComparison`.
- **ClarificationCard** — question text, then either (a) for
  `reason === 'ambiguous_product'`, options grouped under retailer sub-headers
  using `availability_by_retailer` (check-icon chips, matching the
  Shufersal/Tnuva/Tara example in the request), or (b) a flat row of option
  buttons for other reasons. Renders in an "answered" frozen state (selected chip
  highlighted, rest disabled) whenever the turn's `answeredOptionId` is set.
- **RetailerComparison** — two-column responsive grid (stacks to one column below
  `md`) of `RetailerCard`, animated in with a staggered fade/slide.
- **RetailerCard** — initials-in-circle logo placeholder (no real retailer logos),
  retailer name, total price, a savings badge (green) on the cheaper cart, a
  budget-status badge (green "Under budget" / red "Over budget by ₪X" — omitted
  when `budget` is `null`), missing-items list, trade-off-suggestions list, and a
  "Choose {retailer}" button. Gets a blue ring + "Selected" badge once chosen.

## Visual design system

- **Palette:** neutral zinc/slate for structure; emerald green as the primary
  brand accent, doubling as the "cheaper / under budget" semantic color; blue for
  "selected"; red for "over budget" — matching the badge semantics in the
  request.
- **Typography:** Inter (system-ui fallback); large tight-tracked hero headline
  (~`text-5xl`/`text-6xl`); comfortable reading size in bubbles/cards.
- **Shape:** large radii throughout (`rounded-2xl`/`rounded-3xl`) for the hero
  input, chat bubbles, and cards.
- **Elevation:** flat by default; soft shadow reserved for the pinned chat input
  bar and hover states on interactive cards.

## Loading states

- Default: `TypingIndicator` — three sequentially-pulsing dots in a bubble, shown
  for any `status: 'loading'` assistant turn.
- Upgraded: when `expectsComparison` is `true` (previous turn was a
  `retailer_choice` clarification), render a two-card skeleton shaped like
  `RetailerCard` (shadcn `Skeleton` primitives) instead of the dot indicator,
  since the next response is known to be a comparison.

## Animations (Framer Motion)

- Message bubbles/cards: fade + slide-up on mount; retailer card pairs stagger by
  ~80ms.
- Hero → chat transition: hero fades out and collapses height as the thread takes
  over.
- Prompt chips: subtle hover-lift.
- Typing indicator: sequential dot pulse.
- All transitions ~150–250ms; respect `prefers-reduced-motion` (Framer Motion's
  `useReducedMotion`).

## Error handling

- A failed `postChat` call renders an inline error bubble in that turn's place
  (not a page-level banner), with a "Retry" action that re-sends the same
  message/thread_id. This keeps failures contextual to the specific exchange,
  consistent with the chat-thread model.

## Out of scope

- Dark mode / theme toggle.
- RTL layout.
- Any backend/API changes.
- Persisting chat history across page reloads (thread lives in component state
  only, as today).
