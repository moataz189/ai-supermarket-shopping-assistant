# Premium AI Shopping Assistant Frontend Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare-bones `web/` React frontend with a polished, ChatGPT/Perplexity/Instacart-inspired AI shopping assistant UI, without changing the backend API contract.

**Architecture:** A hero landing view (headline, centered input, prompt chips) collapses into a full scrolling chat thread on first send. The thread renders a `turns: Turn[]` array client-side (user bubbles, typing/skeleton loaders, clarification cards, retailer-comparison cards, error bubbles with retry) built from the existing unmodified `ChatResponse` shape returned by `POST /api/chat`.

**Tech Stack:** React 19 + TypeScript + Vite (existing), Tailwind CSS v4 (`@tailwindcss/vite`), shadcn/ui (`new-york` style, neutral base, CSS variables), `lucide-react`, `framer-motion`.

## Global Constraints

- Backend is unchanged: `app/api/routes/chat.py`, `app/api/schemas.py`, and `web/src/api.ts` (types + `postChat`) are not modified. `web/src/format.ts` (`formatRetailerName`) is reused as-is.
- LTR/English UI only — no RTL layout in this iteration.
- Light theme only — no dark mode toggle.
- Full scrolling chat thread — all turns stay visible; answered clarification/retailer cards freeze in place (selected option highlighted, others disabled) rather than disappearing.
- Hero collapses into the chat thread on the first sent message (fade + height-collapse), matching ChatGPT/Perplexity.
- Hero illustration is composed from `lucide-react` icons only — no custom SVG art, no stock imagery, no real retailer logos/branding anywhere in the UI (use a neutral icon avatar for both retailers).
- Badge semantics: green = cheaper/under budget, red = over budget, blue = selected.
- **No frontend test framework exists in this repo** (`web/package.json` has no vitest/testing-library). Do not introduce one for this redesign — that would be scope creep beyond what was requested. Each task's "test cycle" is: TypeScript build (`npm run build`, which runs `tsc -b && vite build` — this also catches unused-var/param errors since `noUnusedLocals`/`noUnusedParameters` are enabled in `tsconfig.app.json`), plus manual verification via the dev server at the milestone tasks called out below (Task 6, Task 13).
- Currency displayed as `₪` (matches the domain — Israeli retailers) formatted with `.toFixed(2)`, consistent with the previous implementation.
- Backend `status` is one of exactly `"success" | "partial_success" | "needs_clarification" | "awaiting_retailer_choice"` (`app/agent/state.py:27`). `clarification.reason` is either `"ambiguous_product"` or `"retailer_choice"` (`app/agent/nodes/resolve_ambiguity.py`, `app/agent/nodes/choose_retailer.py`). For `retailer_choice`, `clarification.options` is always `[{id: "shufersal", label: "Use Shufersal Online"}, {id: "rami_levy", label: "Use Rami Levy Online"}, {id: "decline", label: "Neither — just show me this"}]` and `clarification.carts` holds `RetailerCart` plus a computed `savings_vs_other`. For `ambiguous_product`, `options` are `[{id: <product name>, label: <product name>}, ...]` and `availability_by_retailer` maps retailer → sorted product names available there.
- The value sent back to the backend when answering a clarification/retailer choice **must be the option's `id`** (e.g. `"shufersal"`, `"Tnuva"`, `"decline"`), never its `label` — the backend matches on the raw id (see `app/agent/nodes/choose_retailer.py:22`, `resolve_ambiguity.py:22`). The UI still *displays* the label in the echoed user bubble.

---

### Task 1: Install Tailwind v4 + shadcn/ui + path alias

**Files:**
- Modify: `web/package.json` (new dependencies)
- Modify: `web/vite.config.ts`
- Modify: `web/tsconfig.app.json`
- Create: `web/components.json` (via CLI)
- Create: `web/src/lib/utils.ts` (via CLI)
- Modify: `web/src/index.css` (via CLI, then hand-edited)

**Interfaces:**
- Produces: the `@/*` → `web/src/*` path alias used by every subsequent task's imports; the `cn()` helper at `@/lib/utils`; Tailwind utility classes available project-wide; an emerald-600 `--primary` theme color.

- [ ] **Step 1: Install icon/animation libraries**

```bash
cd web && npm install lucide-react framer-motion
```

- [ ] **Step 2: Run the shadcn/ui init CLI**

```bash
cd web && npx shadcn@latest init -d -y --base-color neutral
```

If the CLI still prompts interactively despite these flags, answer: TypeScript → yes, Style → **New York**, Base color → **Neutral**, CSS variables → **yes**, Would you like to use CSS variables for theming → **yes**. This installs `tailwindcss`, `@tailwindcss/vite`, `tw-animate-css`, `class-variance-authority`, `clsx`, `tailwind-merge` into `web/package.json`, creates `web/components.json` and `web/src/lib/utils.ts`, rewrites `web/src/index.css` with the Tailwind import + shadcn CSS variables, and edits `web/vite.config.ts` + `web/tsconfig.app.json` to add the Tailwind plugin and path alias.

- [ ] **Step 3: Verify/fix `web/vite.config.ts`**

Open the file. It must match this (if the CLI produced something different, edit it to match — keep the existing `server.proxy` block untouched):

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
```

- [ ] **Step 4: Verify/fix `web/tsconfig.app.json`**

Ensure `compilerOptions` includes `"baseUrl": "."` and `"paths": { "@/*": ["./src/*"] }` alongside the existing options (target, lib, module, etc. — leave those untouched):

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023", "DOM"],
    "module": "esnext",
    "types": ["vite/client"],
    "allowArbitraryExtensions": true,
    "skipLibCheck": true,

    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",

    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    },

    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Customize the theme in `web/src/index.css`**

The CLI-generated file defines CSS variables inside a `:root { ... }` block (and usually a `.dark { ... }` block). Make two edits:

1. Inside `:root`, change the `--primary` and `--primary-foreground` lines to:
   ```css
   --primary: oklch(59.6% 0.145 163.225); /* Tailwind emerald-600 */
   --primary-foreground: oklch(1 0 0);
   ```
   and change `--radius` to:
   ```css
   --radius: 1rem;
   ```
2. Delete the entire `.dark { ... }` block — dark mode is out of scope for this redesign (see Global Constraints).

- [ ] **Step 6: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds with no errors (the app still renders the old UI at this point — this step only proves the toolchain is wired correctly).

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json web/vite.config.ts web/tsconfig.app.json web/components.json web/src/lib/utils.ts web/src/index.css
git commit -m "chore(web): add Tailwind v4, shadcn/ui, lucide-react, framer-motion"
```

---

### Task 2: Add shadcn/ui primitive components

**Files:**
- Create (via CLI): `web/src/components/ui/button.tsx`, `card.tsx`, `badge.tsx`, `input.tsx`, `avatar.tsx`, `skeleton.tsx`, `scroll-area.tsx`, `separator.tsx`

**Interfaces:**
- Consumes: `@/lib/utils` (`cn()`) from Task 1.
- Produces: `Button`, `Card`/`CardContent`/etc., `Badge`, `Input`, `Avatar`, `Skeleton`, `ScrollArea`, `Separator` importable from `@/components/ui/<name>`, used by Tasks 5, 7, 9, 10.

- [ ] **Step 1: Add the components**

```bash
cd web && npx shadcn@latest add button card badge input avatar skeleton scroll-area separator --yes
```

- [ ] **Step 2: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds. Confirm the eight files listed above now exist under `web/src/components/ui/`.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ui web/package.json web/package-lock.json
git commit -m "chore(web): add shadcn/ui primitive components"
```

---

### Task 3: Shared `Turn`/`Phase` types

**Files:**
- Create: `web/src/types.ts`

**Interfaces:**
- Consumes: `ChatResponse` from `@/api` (unchanged, existing file).
- Produces: `Turn`, `Phase` types, imported by Tasks 8–12 as `import type { Turn, Phase } from '@/types'`.

- [ ] **Step 1: Write the types**

```ts
import type { ChatResponse } from './api'

export type Turn =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; status: 'loading'; expectsComparison: boolean }
  | {
      id: string
      role: 'assistant'
      status: 'done'
      response: ChatResponse
      answeredOptionId?: string
    }
  | {
      id: string
      role: 'assistant'
      status: 'error'
      errorMessage: string
      retryText: string
      retryDisplayText: string
    }

export type Phase = 'hero' | 'chat'
```

- [ ] **Step 2: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds (the file isn't imported anywhere yet, so this just checks it's syntactically/type valid on its own — `tsc` will still typecheck unreferenced files under `include`).

- [ ] **Step 3: Commit**

```bash
git add web/src/types.ts
git commit -m "feat(web): add Turn/Phase state types for the chat thread"
```

---

### Task 4: `GroceryIllustration` + `NavBar`

**Files:**
- Create: `web/src/components/illustrations/GroceryIllustration.tsx`
- Create: `web/src/components/layout/NavBar.tsx`

**Interfaces:**
- Consumes: `lucide-react`, `framer-motion` (Task 1).
- Produces: `GroceryIllustration` (used by Task 6's `Hero`), `NavBar` (used by Task 12's `App`).

- [ ] **Step 1: Write `GroceryIllustration`**

```tsx
import { Apple, Carrot, Milk, ShoppingCart } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'

const satellites = [
  { Icon: Apple, className: 'top-1 left-2 text-red-500', delay: 0 },
  { Icon: Carrot, className: 'bottom-4 left-0 text-orange-500', delay: 0.4 },
  { Icon: Milk, className: 'top-4 right-0 text-blue-400', delay: 0.8 },
]

export function GroceryIllustration() {
  const reduceMotion = useReducedMotion()

  return (
    <div className="relative mx-auto h-40 w-40 sm:h-48 sm:w-48">
      <div className="absolute inset-0 rounded-full bg-emerald-100" />
      <motion.div
        className="absolute inset-0 flex items-center justify-center"
        animate={reduceMotion ? undefined : { y: [0, -8, 0] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
      >
        <ShoppingCart className="h-16 w-16 text-emerald-600" strokeWidth={1.5} />
      </motion.div>
      {satellites.map(({ Icon, className, delay }) => (
        <motion.div
          key={className}
          className={`absolute rounded-full bg-white p-2 shadow-sm ${className}`}
          animate={reduceMotion ? undefined : { y: [0, -6, 0] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut', delay }}
        >
          <Icon className="h-5 w-5" strokeWidth={1.5} />
        </motion.div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Write `NavBar`**

```tsx
import { ShoppingBasket } from 'lucide-react'

export function NavBar() {
  return (
    <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-600 text-white">
          <ShoppingBasket className="h-5 w-5" strokeWidth={2} />
        </span>
        <span className="text-lg font-semibold text-zinc-900">AI Supermarket Assistant</span>
      </div>
    </header>
  )
}
```

- [ ] **Step 3: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/illustrations web/src/components/layout/NavBar.tsx
git commit -m "feat(web): add hero illustration and nav bar"
```

---

### Task 5: `ChatInput` + `PromptChips`

**Files:**
- Create: `web/src/components/chat/ChatInput.tsx`
- Create: `web/src/components/chat/PromptChips.tsx`

**Interfaces:**
- Consumes: `Input` from `@/components/ui/input` (Task 2).
- Produces: `ChatInput({ variant: 'hero' | 'bar', onSend, disabled?, placeholder? })`, `PromptChips({ onSelect, disabled? })` — both used by Task 6 (`Hero`) and Task 12 (`App`, `variant="bar"`).

- [ ] **Step 1: Write `ChatInput`**

```tsx
import { useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUp } from 'lucide-react'
import { Input } from '@/components/ui/input'

interface ChatInputProps {
  variant: 'hero' | 'bar'
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({ variant, onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  const isHero = variant === 'hero'

  return (
    <form
      onSubmit={handleSubmit}
      className={
        isHero
          ? 'mx-auto flex w-full max-w-2xl items-center gap-2 rounded-3xl border border-zinc-200 bg-white p-2 shadow-lg shadow-zinc-200/50'
          : 'mx-auto flex w-full max-w-3xl items-center gap-2 rounded-3xl border border-zinc-200 bg-white p-2 shadow-md'
      }
    >
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        placeholder={placeholder ?? 'e.g. pasta for 4 people, budget 100'}
        className={
          isHero
            ? 'h-12 flex-1 rounded-2xl border-0 text-base shadow-none focus-visible:ring-0'
            : 'h-11 flex-1 rounded-2xl border-0 shadow-none focus-visible:ring-0'
        }
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
      >
        <ArrowUp className="h-5 w-5" />
      </button>
    </form>
  )
}
```

- [ ] **Step 2: Write `PromptChips`**

```tsx
import { motion } from 'framer-motion'

const PROMPTS = [
  'Pasta for 4 people',
  'Weekly shopping under ₪250',
  'Gluten-free breakfast',
  'Chicken, rice and vegetables',
]

interface PromptChipsProps {
  onSelect: (prompt: string) => void
  disabled?: boolean
}

export function PromptChips({ onSelect, disabled }: PromptChipsProps) {
  return (
    <div className="mt-4 flex flex-wrap justify-center gap-2">
      {PROMPTS.map((prompt) => (
        <motion.button
          key={prompt}
          type="button"
          disabled={disabled}
          whileHover={disabled ? undefined : { y: -2 }}
          onClick={() => onSelect(prompt)}
          className="rounded-full border border-zinc-200 bg-white px-4 py-2 text-sm text-zinc-700 shadow-sm transition hover:border-emerald-300 hover:text-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {prompt}
        </motion.button>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/chat/ChatInput.tsx web/src/components/chat/PromptChips.tsx
git commit -m "feat(web): add chat input and prompt chips"
```

---

### Task 6: `Hero`

**Files:**
- Create: `web/src/components/layout/Hero.tsx`

**Interfaces:**
- Consumes: `GroceryIllustration` (Task 4), `ChatInput`, `PromptChips` (Task 5), `motion` from `framer-motion`.
- Produces: `Hero({ onSend, disabled? })`, used by Task 12 (`App`), wrapped in `AnimatePresence` there so `exit` fires.

- [ ] **Step 1: Write `Hero`**

```tsx
import { motion } from 'framer-motion'
import { GroceryIllustration } from '@/components/illustrations/GroceryIllustration'
import { ChatInput } from '@/components/chat/ChatInput'
import { PromptChips } from '@/components/chat/PromptChips'

interface HeroProps {
  onSend: (text: string) => void
  disabled?: boolean
}

export function Hero({ onSend, disabled }: HeroProps) {
  return (
    <motion.section
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25, ease: 'easeInOut' }}
      className="mx-auto flex max-w-3xl flex-col items-center overflow-hidden px-4 pb-16 pt-16 text-center sm:pt-24"
    >
      <GroceryIllustration />
      <h1 className="mt-6 text-4xl font-semibold tracking-tight text-zinc-900 sm:text-5xl">
        AI Supermarket Shopping Assistant
      </h1>
      <p className="mt-3 text-lg text-zinc-500">Compare Shufersal and Rami Levy instantly using AI.</p>
      <div className="mt-8 w-full">
        <ChatInput variant="hero" onSend={onSend} disabled={disabled} />
        <PromptChips onSelect={onSend} disabled={disabled} />
      </div>
    </motion.section>
  )
}
```

- [ ] **Step 2: Temporarily wire into `App.tsx` for a visual check**

This is the first visually-verifiable milestone. Temporarily replace the body of `web/src/App.tsx`'s `return` with just `<Hero onSend={() => {}} />` (leave the rest of `App.tsx` untouched — Task 12 does the real rewrite). Run:

```bash
cd web && npm run dev
```

Open the printed local URL in a browser. Expected: centered headline "AI Supermarket Shopping Assistant", subheadline, floating cart+produce illustration, large rounded input, four prompt chips below it — all centered, light background. Check responsiveness by narrowing the browser window.

- [ ] **Step 3: Revert the temporary wiring**

Undo the Step 2 edit to `App.tsx` (`git checkout -- web/src/App.tsx` or manually revert) — it must be byte-identical to before this step, since Task 12 owns the real `App.tsx` rewrite.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/layout/Hero.tsx
git commit -m "feat(web): add hero section"
```

---

### Task 7: `TypingIndicator` + retailer comparison skeleton

**Files:**
- Create: `web/src/components/chat/TypingIndicator.tsx`
- Create: `web/src/components/retailers/RetailerCardSkeleton.tsx`

**Interfaces:**
- Consumes: `Skeleton` from `@/components/ui/skeleton` (Task 2), `motion` from `framer-motion`.
- Produces: `TypingIndicator`, `RetailerCardSkeleton`, `RetailerComparisonSkeleton` — used by Task 11 (`MessageThread`) for `status: 'loading'` turns.

- [ ] **Step 1: Write `TypingIndicator`**

```tsx
import { motion } from 'framer-motion'

function dotTransition(delay: number) {
  return {
    duration: 0.6,
    repeat: Infinity,
    repeatType: 'loop' as const,
    ease: 'easeInOut' as const,
    delay,
  }
}

export function TypingIndicator() {
  return (
    <div className="flex w-fit items-center gap-1 rounded-3xl rounded-bl-md bg-zinc-100 px-4 py-3">
      {[0, 0.15, 0.3].map((delay) => (
        <motion.span
          key={delay}
          className="h-2 w-2 rounded-full bg-zinc-400"
          animate={{ y: [0, -4, 0] }}
          transition={dotTransition(delay)}
        />
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Write `RetailerCardSkeleton`**

```tsx
import { Skeleton } from '@/components/ui/skeleton'

export function RetailerCardSkeleton() {
  return (
    <div className="rounded-3xl border border-zinc-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10 rounded-full" />
        <Skeleton className="h-5 w-28" />
      </div>
      <Skeleton className="mt-4 h-8 w-32" />
      <Skeleton className="mt-3 h-5 w-24 rounded-full" />
      <div className="mt-4 space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-5/6" />
      </div>
      <Skeleton className="mt-4 h-10 w-full rounded-xl" />
    </div>
  )
}

export function RetailerComparisonSkeleton() {
  return (
    <div className="grid w-full max-w-3xl gap-4 sm:grid-cols-2">
      <RetailerCardSkeleton />
      <RetailerCardSkeleton />
    </div>
  )
}
```

- [ ] **Step 3: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/chat/TypingIndicator.tsx web/src/components/retailers/RetailerCardSkeleton.tsx
git commit -m "feat(web): add typing indicator and retailer comparison skeleton"
```

---

### Task 8: `UserBubble` + `AssistantBubble`

**Files:**
- Create: `web/src/components/chat/UserBubble.tsx`
- Create: `web/src/components/chat/AssistantBubble.tsx`

**Interfaces:**
- Consumes: `motion` from `framer-motion`.
- Produces: `UserBubble({ text })`, `AssistantBubble({ children })` — used by Task 11 (`MessageThread`).

- [ ] **Step 1: Write `UserBubble`**

```tsx
import { motion } from 'framer-motion'

export function UserBubble({ text }: { text: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex justify-end"
    >
      <div className="max-w-[80%] rounded-3xl rounded-br-md bg-emerald-600 px-4 py-2.5 text-white">{text}</div>
    </motion.div>
  )
}
```

- [ ] **Step 2: Write `AssistantBubble`**

```tsx
import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

export function AssistantBubble({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex justify-start"
    >
      <div className="max-w-[80%] rounded-3xl rounded-bl-md bg-zinc-100 px-4 py-2.5 text-zinc-800">{children}</div>
    </motion.div>
  )
}
```

- [ ] **Step 3: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/chat/UserBubble.tsx web/src/components/chat/AssistantBubble.tsx
git commit -m "feat(web): add user and assistant chat bubbles"
```

---

### Task 9: `OptionChip` + `ClarificationCard`

**Files:**
- Create: `web/src/components/clarification/OptionChip.tsx`
- Create: `web/src/components/clarification/ClarificationCard.tsx`

**Interfaces:**
- Consumes: `Clarification` type from `@/api` (existing), `formatRetailerName` from `@/format` (existing).
- Produces: `ClarificationCard({ clarification, answeredOptionId?, onSelect? })` — used by Task 11 (`MessageThread`) for `clarification.reason === 'ambiguous_product'` (and any reason other than `'retailer_choice'`, as a defensive fallback).

- [ ] **Step 1: Write `OptionChip`**

```tsx
import { Check } from 'lucide-react'

interface OptionChipProps {
  label: string
  selected?: boolean
  disabled?: boolean
  onClick?: () => void
}

export function OptionChip({ label, selected, disabled, onClick }: OptionChipProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition disabled:cursor-default ${
        selected
          ? 'border-blue-400 bg-blue-50 text-blue-700'
          : 'border-zinc-200 bg-white text-zinc-700 hover:border-emerald-300 hover:text-emerald-700'
      } ${disabled && !selected ? 'opacity-40' : ''}`}
    >
      <Check className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}
```

- [ ] **Step 2: Write `ClarificationCard`**

```tsx
import { OptionChip } from './OptionChip'
import type { Clarification } from '@/api'
import { formatRetailerName } from '@/format'

interface ClarificationCardProps {
  clarification: Clarification
  answeredOptionId?: string
  onSelect?: (optionId: string) => void
}

export function ClarificationCard({ clarification, answeredOptionId, onSelect }: ClarificationCardProps) {
  const { question, options, availability_by_retailer } = clarification
  const answered = Boolean(answeredOptionId)

  return (
    <div className="w-full max-w-lg rounded-3xl border border-zinc-200 bg-white p-5">
      <p className="font-medium text-zinc-900">{question}</p>

      {availability_by_retailer ? (
        <div className="mt-4 space-y-4">
          {Object.entries(availability_by_retailer).map(([retailer, names]) => (
            <div key={retailer}>
              <p className="mb-2 text-sm font-medium text-zinc-500">{formatRetailerName(retailer)}</p>
              <div className="flex flex-wrap gap-2">
                {options
                  .filter((option) => names.includes(option.id))
                  .map((option) => (
                    <OptionChip
                      key={`${retailer}-${option.id}`}
                      label={option.label}
                      selected={answeredOptionId === option.id}
                      disabled={answered}
                      onClick={onSelect ? () => onSelect(option.id) : undefined}
                    />
                  ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          {options.map((option) => (
            <OptionChip
              key={option.id}
              label={option.label}
              selected={answeredOptionId === option.id}
              disabled={answered}
              onClick={onSelect ? () => onSelect(option.id) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/clarification
git commit -m "feat(web): add clarification card with retailer-grouped option chips"
```

---

### Task 10: `RetailerCard` + `RetailerComparison`

**Files:**
- Create: `web/src/components/retailers/RetailerCard.tsx`
- Create: `web/src/components/retailers/RetailerComparison.tsx`

**Interfaces:**
- Consumes: `RetailerCart`, `ClarificationOption` types from `@/api` (existing), `formatRetailerName` from `@/format` (existing), `Badge` from `@/components/ui/badge` (Task 2).
- Produces: `RetailerCard({ retailer, cart, selected?, onChoose?, chooseLabel? })`, `RetailerComparison({ carts, chosenRetailer?, options?, answeredOptionId?, onChoose? })` — used by Task 11 (`MessageThread`) for both the mid-conversation `retailer_choice` clarification and the terminal result.

- [ ] **Step 1: Write `RetailerCard`**

```tsx
import { Store } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { RetailerCart } from '@/api'
import { formatRetailerName } from '@/format'

interface RetailerCardProps {
  retailer: string
  cart: RetailerCart
  selected?: boolean
  onChoose?: () => void
  chooseLabel?: string
}

export function RetailerCard({ retailer, cart, selected, onChoose, chooseLabel }: RetailerCardProps) {
  const name = formatRetailerName(retailer)
  const overBudget = cart.over_budget_by != null
  const hasSavings = cart.savings_vs_other != null && cart.savings_vs_other > 0

  return (
    <div
      className={`flex flex-col rounded-3xl border bg-white p-5 transition ${
        selected ? 'border-blue-400 ring-2 ring-blue-200' : 'border-zinc-200'
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100 text-zinc-500">
          <Store className="h-5 w-5" aria-hidden />
        </span>
        <span className="text-lg font-semibold text-zinc-900">{name}</span>
        {selected && (
          <Badge variant="secondary" className="ml-auto bg-blue-100 text-blue-700 hover:bg-blue-100">
            Selected
          </Badge>
        )}
      </div>

      <p className="mt-4 text-3xl font-bold text-zinc-900">₪{cart.total.toFixed(2)}</p>

      <div className="mt-2 flex flex-wrap gap-2">
        {hasSavings && (
          <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
            Save ₪{cart.savings_vs_other!.toFixed(2)}
          </Badge>
        )}
        {cart.budget != null && (
          <Badge
            variant="secondary"
            className={
              overBudget
                ? 'bg-red-100 text-red-700 hover:bg-red-100'
                : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-100'
            }
          >
            {overBudget ? `Over budget by ₪${cart.over_budget_by!.toFixed(2)}` : 'Under budget'}
          </Badge>
        )}
      </div>

      <ul className="mt-4 space-y-1 text-sm text-zinc-600">
        {cart.items.map((line) => (
          <li key={line.item_code} className="flex justify-between gap-2">
            <span className="truncate">
              {line.product_name} × {line.qty}
            </span>
            <span className="shrink-0 text-zinc-900">₪{line.subtotal.toFixed(2)}</span>
          </li>
        ))}
      </ul>

      {cart.missing_items.length > 0 && (
        <p className="mt-3 text-sm text-zinc-500">
          <span className="font-medium text-zinc-700">Missing: </span>
          {cart.missing_items.map((item) => String(item.name)).join(', ')}
        </p>
      )}

      {cart.trade_off_suggestions.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-zinc-500">
          {cart.trade_off_suggestions.map((s, i) => (
            <li key={i}>
              Swap {String(s.current_choice)} for {String(s.suggested_choice)} to save ₪
              {Number(s.savings).toFixed(2)}
            </li>
          ))}
        </ul>
      )}

      {onChoose && (
        <button
          type="button"
          onClick={onChoose}
          className="mt-4 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-emerald-700"
        >
          {chooseLabel ?? `Choose ${name}`}
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Write `RetailerComparison`**

```tsx
import { motion } from 'framer-motion'
import { RetailerCard } from './RetailerCard'
import type { ClarificationOption, RetailerCart } from '@/api'

interface RetailerComparisonProps {
  carts: Record<string, RetailerCart>
  chosenRetailer?: string | null
  options?: ClarificationOption[]
  answeredOptionId?: string
  onChoose?: (optionId: string) => void
}

export function RetailerComparison({
  carts,
  chosenRetailer,
  options,
  answeredOptionId,
  onChoose,
}: RetailerComparisonProps) {
  const entries = Object.entries(carts)
  const isInteractive = Boolean(onChoose) && !answeredOptionId
  const declineOption = options?.find((o) => o.id === 'decline')

  return (
    <div className="w-full max-w-3xl">
      <motion.div
        initial="hidden"
        animate="visible"
        variants={{ visible: { transition: { staggerChildren: 0.08 } } }}
        className="grid gap-4 sm:grid-cols-2"
      >
        {entries.map(([retailer, cart]) => {
          const option = options?.find((o) => o.id === retailer)
          return (
            <motion.div key={retailer} variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0 } }}>
              <RetailerCard
                retailer={retailer}
                cart={cart}
                selected={chosenRetailer === retailer || answeredOptionId === retailer}
                chooseLabel={option?.label}
                onChoose={isInteractive ? () => onChoose!(retailer) : undefined}
              />
            </motion.div>
          )
        })}
      </motion.div>

      {isInteractive && declineOption && (
        <button
          type="button"
          onClick={() => onChoose!(declineOption.id)}
          className="mt-4 text-sm text-zinc-500 underline-offset-4 hover:text-zinc-700 hover:underline"
        >
          {declineOption.label}
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/retailers/RetailerCard.tsx web/src/components/retailers/RetailerComparison.tsx
git commit -m "feat(web): add retailer card and side-by-side comparison"
```

---

### Task 11: `MessageThread`

**Files:**
- Create: `web/src/components/chat/MessageThread.tsx`

**Interfaces:**
- Consumes: `Turn` from `@/types` (Task 3); `UserBubble`, `AssistantBubble`, `TypingIndicator` (Tasks 7–8); `ClarificationCard` (Task 9); `RetailerComparison`, `RetailerComparisonSkeleton` (Tasks 7, 10).
- Produces: `MessageThread({ turns, onSelectOption, onRetry })` where `onSelectOption: (turnId: string, optionId: string, label: string) => void` and `onRetry: (turnId: string) => void` — used by Task 12 (`App`).

- [ ] **Step 1: Write `MessageThread`**

```tsx
import { useEffect, useRef } from 'react'
import { AnimatePresence } from 'framer-motion'
import type { Turn } from '@/types'
import { UserBubble } from './UserBubble'
import { AssistantBubble } from './AssistantBubble'
import { TypingIndicator } from './TypingIndicator'
import { ClarificationCard } from '@/components/clarification/ClarificationCard'
import { RetailerComparison } from '@/components/retailers/RetailerComparison'
import { RetailerComparisonSkeleton } from '@/components/retailers/RetailerCardSkeleton'

interface MessageThreadProps {
  turns: Turn[]
  onSelectOption: (turnId: string, optionId: string, label: string) => void
  onRetry: (turnId: string) => void
}

function leadText(status: string): string {
  return status === 'partial_success'
    ? "Here's what I found — a couple of items needed a substitution:"
    : "Here's your comparison:"
}

export function MessageThread({ turns, onSelectOption, onRetry }: MessageThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
      <AnimatePresence initial={false}>
        {turns.map((turn) => {
          if (turn.role === 'user') {
            return <UserBubble key={turn.id} text={turn.text} />
          }

          if (turn.status === 'loading') {
            return (
              <div key={turn.id} className="flex justify-start">
                {turn.expectsComparison ? <RetailerComparisonSkeleton /> : <TypingIndicator />}
              </div>
            )
          }

          if (turn.status === 'error') {
            return (
              <AssistantBubble key={turn.id}>
                <p className="text-red-700">{turn.errorMessage}</p>
                <button
                  type="button"
                  onClick={() => onRetry(turn.id)}
                  className="mt-2 text-sm font-medium text-red-700 underline underline-offset-4"
                >
                  Retry
                </button>
              </AssistantBubble>
            )
          }

          const { response, answeredOptionId } = turn
          const clarification = response.clarification

          if (clarification && clarification.reason === 'retailer_choice' && clarification.carts) {
            const carts = clarification.carts
            return (
              <div key={turn.id} className="flex justify-start">
                <RetailerComparison
                  carts={carts}
                  options={clarification.options}
                  answeredOptionId={answeredOptionId}
                  onChoose={(optionId) => {
                    const label = clarification.options.find((o) => o.id === optionId)?.label ?? optionId
                    onSelectOption(turn.id, optionId, label)
                  }}
                />
              </div>
            )
          }

          if (clarification) {
            return (
              <div key={turn.id} className="flex justify-start">
                <ClarificationCard
                  clarification={clarification}
                  answeredOptionId={answeredOptionId}
                  onSelect={(optionId) => {
                    const label = clarification.options.find((o) => o.id === optionId)?.label ?? optionId
                    onSelectOption(turn.id, optionId, label)
                  }}
                />
              </div>
            )
          }

          if (response.carts) {
            return (
              <div key={turn.id} className="flex flex-col gap-3">
                <AssistantBubble>{leadText(response.status)}</AssistantBubble>
                <div className="flex justify-start">
                  <RetailerComparison carts={response.carts} chosenRetailer={response.chosen_retailer} />
                </div>
                {response.warnings.length > 0 && (
                  <AssistantBubble>
                    <ul className="list-disc space-y-1 pl-4 text-sm">
                      {response.warnings.map((w, i) => (
                        <li key={i}>{JSON.stringify(w)}</li>
                      ))}
                    </ul>
                  </AssistantBubble>
                )}
              </div>
            )
          }

          return <AssistantBubble key={turn.id}>All done.</AssistantBubble>
        })}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  )
}
```

- [ ] **Step 2: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/chat/MessageThread.tsx
git commit -m "feat(web): add message thread that dispatches turns to bubbles and cards"
```

---

### Task 12: Rewrite `App.tsx`

**Files:**
- Modify: `web/src/App.tsx` (full rewrite)

**Interfaces:**
- Consumes: `NavBar` (Task 4), `Hero` (Task 6), `MessageThread`, `ChatInput` (Tasks 5, 11), `postChat` from `@/api` (existing, unchanged), `Turn`/`Phase` from `@/types` (Task 3).
- Produces: the running application — no further tasks consume `App.tsx` directly.

- [ ] **Step 1: Replace the contents of `web/src/App.tsx`**

```tsx
import { useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { NavBar } from '@/components/layout/NavBar'
import { Hero } from '@/components/layout/Hero'
import { MessageThread } from '@/components/chat/MessageThread'
import { ChatInput } from '@/components/chat/ChatInput'
import { postChat } from '@/api'
import type { Phase, Turn } from '@/types'

function newId() {
  return crypto.randomUUID()
}

function App() {
  const [phase, setPhase] = useState<Phase>('hero')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])

  const isBusy = turns.some((t) => t.role === 'assistant' && t.status === 'loading')

  async function attempt(loadingId: string, apiText: string, expectsComparison: boolean, retryDisplayText: string) {
    setTurns((prev) =>
      prev.map((t) =>
        t.id === loadingId ? { id: loadingId, role: 'assistant', status: 'loading', expectsComparison } : t,
      ),
    )
    try {
      const response = await postChat(threadId, apiText)
      setThreadId(response.thread_id)
      setTurns((prev) =>
        prev.map((t) => (t.id === loadingId ? { id: loadingId, role: 'assistant', status: 'done', response } : t)),
      )
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : 'Something went wrong'
      setTurns((prev) =>
        prev.map((t) =>
          t.id === loadingId
            ? {
                id: loadingId,
                role: 'assistant',
                status: 'error',
                errorMessage,
                retryText: apiText,
                retryDisplayText,
              }
            : t,
        ),
      )
    }
  }

  function sendMessage(displayText: string, apiText: string, expectsComparison: boolean) {
    const userTurn: Turn = { id: newId(), role: 'user', text: displayText }
    const loadingId = newId()
    const loadingTurn: Turn = { id: loadingId, role: 'assistant', status: 'loading', expectsComparison }
    setTurns((prev) => [...prev, userTurn, loadingTurn])
    setPhase('chat')
    void attempt(loadingId, apiText, expectsComparison, displayText)
  }

  function handleSend(text: string) {
    sendMessage(text, text, false)
  }

  function handleSelectOption(turnId: string, optionId: string, label: string) {
    const turn = turns.find((t) => t.id === turnId)
    const expectsComparison =
      turn?.role === 'assistant' && turn.status === 'done'
        ? turn.response.clarification?.reason === 'retailer_choice'
        : false

    setTurns((prev) =>
      prev.map((t) =>
        t.id === turnId && t.role === 'assistant' && t.status === 'done' ? { ...t, answeredOptionId: optionId } : t,
      ),
    )
    sendMessage(label, optionId, expectsComparison)
  }

  function handleRetry(turnId: string) {
    const turn = turns.find((t) => t.id === turnId)
    if (!turn || turn.role !== 'assistant' || turn.status !== 'error') return
    void attempt(turnId, turn.retryText, false, turn.retryDisplayText)
  }

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50">
      <NavBar />
      <AnimatePresence>{phase === 'hero' && <Hero onSend={handleSend} disabled={isBusy} />}</AnimatePresence>
      {phase === 'chat' && (
        <div className="flex flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
            <MessageThread turns={turns} onSelectOption={handleSelectOption} onRetry={handleRetry} />
          </div>
          <div className="sticky bottom-0 border-t border-zinc-200 bg-zinc-50/95 px-4 py-4 backdrop-blur">
            <ChatInput variant="bar" onSend={handleSend} disabled={isBusy} />
          </div>
        </div>
      )}
    </div>
  )
}

export default App
```

- [ ] **Step 2: Verify the build**

```bash
cd web && npm run build
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add web/src/App.tsx
git commit -m "feat(web): wire hero-to-chat state machine into App"
```

---

### Task 13: Full manual browser verification

**Files:** none (verification only).

- [ ] **Step 1: Start both servers**

```bash
# terminal 1, from repo root
uvicorn app.api.main:app --reload
# terminal 2
cd web && npm run dev
```

- [ ] **Step 2: Walk the golden path**

In the browser: confirm the hero renders (headline, illustration, input, chips). Click a prompt chip (e.g. "Chicken, rice and vegetables"). Confirm: hero fades/collapses, a user bubble appears on the right with the chip text, a typing indicator appears on the left, then either a clarification card, a retailer-choice comparison (two cards, savings/budget badges, "Choose X" buttons, decline link), or a final comparison appears. If a clarification/retailer-choice card appears, click an option and confirm: the card freezes (selected option highlighted, others disabled/dimmed), a new user bubble appears with the chosen label, a loading indicator appears (skeleton if the previous card was the retailer-choice one), then the next turn renders.

- [ ] **Step 3: Check edge cases**

- Type a free-text message in the bottom input bar once in chat mode; confirm it sends and appends normally.
- Stop the backend (`Ctrl+C` on the uvicorn process) and send a message; confirm an inline red error bubble with a "Retry" button appears (not a page-level crash). Restart the backend and click "Retry"; confirm it re-sends without duplicating the user bubble and resolves normally.
- Resize the browser to a narrow (mobile) width; confirm the hero, chat bubbles, and retailer cards (stacked to one column) remain usable with no horizontal overflow.
- With OS "reduce motion" enabled (or via browser devtools emulation of `prefers-reduced-motion: reduce`), confirm the hero illustration and typing indicator no longer animate but remain visible/usable.

- [ ] **Step 4: Report results**

Note any visual or functional issues found; fix them in the relevant component file from Tasks 4–12 before proceeding to Task 14. This task has no commit of its own — fixes get committed as part of whichever task's file they touch (`git commit --fixup` is not required; a small follow-up commit referencing the fix is fine).

---

### Task 14: Remove superseded files and finalize

**Files:**
- Delete: `web/src/App.css`
- Delete: `web/src/components/ClarificationPrompt.tsx`
- Delete: `web/src/components/RetailerCartsView.tsx`

**Interfaces:** none — this task only removes dead code now fully replaced by Tasks 9–11.

- [ ] **Step 1: Confirm nothing still imports the old files**

```bash
cd web && grep -rn "ClarificationPrompt\|RetailerCartsView\|App.css" src
```

Expected: no matches (Task 12's rewritten `App.tsx` no longer imports `App.css`, `ClarificationPrompt`, or `RetailerCartsView`).

- [ ] **Step 2: Delete the files**

```bash
cd web && rm src/App.css src/components/ClarificationPrompt.tsx src/components/RetailerCartsView.tsx
```

- [ ] **Step 3: Lint and build**

```bash
cd web && npm run lint && npm run build
```

Expected: both succeed with no errors.

- [ ] **Step 4: Commit**

```bash
git add -u web/src
git commit -m "chore(web): remove superseded pre-redesign components and styles"
```

---

## Self-review notes

- **Spec coverage:** nav bar (Task 4), hero + headline/subheadline/illustration/input/chips (Tasks 4–6), user-right/AI-left bubbles + typing indicator + loading skeleton (Tasks 7–8, 11), clarification cards with retailer-grouped checkmark chips (Task 9), two-card retailer comparison with logo placeholder/total/savings badge/budget badge/missing items/trade-offs/choose button (Task 10), colored badge semantics green/red/blue (Task 10), animations on messages/clarification/retailer cards/loading (Tasks 6–11 via `framer-motion`), desktop-first responsive layout (Tailwind `sm:`/`grid` breakpoints throughout), backend untouched (Global Constraints + no task touches `app/`).
- **Type consistency checked:** `Turn` (Task 3) fields (`expectsComparison`, `answeredOptionId`, `errorMessage`/`retryText`/`retryDisplayText`) match exactly how Task 11 (`MessageThread`) and Task 12 (`App`) read/write them. `RetailerComparison`/`RetailerCard`/`ClarificationCard` prop names match exactly between their definitions (Tasks 9–10) and call sites (Task 11).
- **Known simplification:** retry (Task 12) re-runs the failed turn in place rather than appending a new user bubble — this avoids duplicating the user's message on retry, which a naive "just call sendMessage again" implementation would have done.
