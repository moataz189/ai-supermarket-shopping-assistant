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
      // Only set after answering an 'ambiguous_product' clarification (CP9 follow-up,
      // 2026-08-08) — one chosen option id per retailer, e.g. { shufersal: 'Tara' }.
      answeredByRetailer?: Record<string, string>
      // Only set after answering a 'recipe_ingredient_selection' clarification (CP10) —
      // the ingredient ids the user chose to buy.
      answeredIngredientIds?: string[]
    }
  | {
      id: string
      role: 'assistant'
      status: 'error'
      errorMessage: string
      retryText: string
      retryDisplayText: string
      requestThreadId: string | null
    }

export type Phase = 'hero' | 'chat'
