import type { ChatResponse, RecipeInstructionsResponse } from './api'

// Tracks the "Would you like to see how to prepare X?" offer on a completed recipe
// turn (see MessageThread.tsx) — undefined means the offer hasn't been acted on yet.
// Fetching is a plain stateless call to POST /recipe-instructions (see
// app/api/routes/recipe.py), entirely independent of the LangGraph thread/checkpointer,
// so it's tracked here rather than by re-sending a chat message.
export interface RecipeInstructionsState {
  status: 'loading' | 'loaded' | 'error'
  data?: RecipeInstructionsResponse
}

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
      instructions?: RecipeInstructionsState
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
