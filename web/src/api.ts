export interface ClarificationOption {
  id: string
  label: string
  price?: number | null
}

export interface RecipeIngredient {
  name: string
  quantity?: number | null
  unit?: string | null
}

export interface RecipeInfo {
  title?: string | null
  servings?: number | null
  ingredients: RecipeIngredient[]
}

export interface IngredientSelectionOption {
  id: string
  name: string
  display_name: string
  quantity?: number | null
  unit?: string | null
  selected: boolean
}

export interface Clarification {
  reason: string
  question: string
  options: ClarificationOption[]
  carts?: Record<string, RetailerCart> | null
  // Only set for reason === 'ambiguous_product' (CP9 follow-up, 2026-08-08) — each
  // retailer's own independent candidate set (with price), for a retailer that's
  // genuinely ambiguous on its own candidates. A retailer already auto-resolved (or with
  // no candidates at all) is simply absent — never asked about.
  options_by_retailer?: Record<string, ClarificationOption[]> | null
  // Only set for reason === 'recipe_ingredient_selection' (CP10) — the full scaled
  // recipe ingredient list, each pre-selected. The resume answer is the selected ids as
  // a JSON array (see App.tsx's handleSelectIngredients), not free text.
  ingredients?: IngredientSelectionOption[] | null
  recipe?: RecipeInfo | null
}

export interface CartLine {
  name: string
  item_code: string
  product_name: string
  unit_price: number
  qty: number
  subtotal: number
  link?: string | null
  requested_quantity?: number | null
  requested_unit?: string | null
}

export interface RetailerCart {
  retailer: string
  items: CartLine[]
  missing_items: Record<string, unknown>[]
  total: number
  budget: number | null
  over_budget_by: number | null
  trade_off_suggestions: Record<string, unknown>[]
  savings_vs_other?: number
}

export interface RetailerCartItemResult {
  name: string
  item_code: string
  status: string
  reason?: string | null
  matched_by?: string | null
  quantity_confirmed?: number | null
  requested_quantity?: number | null
  requested_unit?: string | null
  cart_quantity?: number | null
  cart_unit?: string | null
}

export interface RetailerCartResult {
  retailer: string
  added: RetailerCartItemResult[]
  failed: RetailerCartItemResult[]
  blocked: boolean
  blocked_reason?: string | null
  cart_url?: string | null
}

export interface ChatResponse {
  thread_id: string
  status: string
  clarification?: Clarification | null
  carts?: Record<string, RetailerCart> | null
  chosen_retailer?: string | null
  retailer_cart_result?: RetailerCartResult | null
  warnings: Record<string, unknown>[]
  message?: string | null
  recipe?: RecipeInfo | null
}

export async function postChat(threadId: string | null, message: string): Promise<ChatResponse> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: threadId, message }),
  })
  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status}`)
  }
  return (await response.json()) as ChatResponse
}
