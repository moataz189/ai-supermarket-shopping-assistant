import { useEffect, useRef } from 'react'
import { AnimatePresence } from 'framer-motion'
import type { Turn } from '@/types'
import { UserBubble } from './UserBubble'
import { AssistantBubble } from './AssistantBubble'
import { TypingIndicator } from './TypingIndicator'
import { ClarificationCard } from '@/components/clarification/ClarificationCard'
import { IngredientSelectionCard } from '@/components/clarification/IngredientSelectionCard'
import { RetailerComparison } from '@/components/retailers/RetailerComparison'
import { RetailerComparisonSkeleton } from '@/components/retailers/RetailerCardSkeleton'
import { RetailerCartResultView } from '@/components/RetailerCartResultView'
import { RecipeIngredientsView } from '@/components/RecipeIngredientsView'
import { WarningsList } from './WarningsList'
import { formatRetailerName } from '@/format'

interface MessageThreadProps {
  turns: Turn[]
  onSelectOption: (turnId: string, optionId: string, label: string) => void
  onSelectMultipleOption: (turnId: string, answersByRetailer: Record<string, string>, displayLabel: string) => void
  onSelectIngredients: (turnId: string, selectedIds: string[], displayLabel: string) => void
  onRetry: (turnId: string) => void
}

function leadText(status: string): string {
  return status === 'partial_success'
    ? "Here's what I found — a couple of items needed a substitution:"
    : "Here's your comparison:"
}

export function MessageThread({
  turns,
  onSelectOption,
  onSelectMultipleOption,
  onSelectIngredients,
  onRetry,
}: MessageThreadProps) {
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

          const { response, answeredOptionId, answeredByRetailer, answeredIngredientIds } = turn
          const clarification = response.clarification

          if (clarification && clarification.reason === 'recipe_ingredient_selection') {
            return (
              <div key={turn.id} className="flex justify-start">
                <IngredientSelectionCard
                  clarification={clarification}
                  answeredIngredientIds={answeredIngredientIds}
                  onConfirm={(selectedIds) => {
                    const byId = new Map((clarification.ingredients ?? []).map((i) => [i.id, i.display_name]))
                    const displayLabel =
                      selectedIds.length === 0
                        ? 'None — I already have everything'
                        : selectedIds.map((id) => byId.get(id) ?? id).join(', ')
                    onSelectIngredients(turn.id, selectedIds, displayLabel)
                  }}
                />
              </div>
            )
          }

          if (clarification && clarification.reason === 'retailer_choice' && clarification.carts) {
            const carts = clarification.carts
            return (
              <div key={turn.id} className="flex flex-col gap-3">
                {clarification.recipe && (
                  <div className="flex justify-start">
                    <RecipeIngredientsView recipe={clarification.recipe} />
                  </div>
                )}
                <div className="flex justify-start">
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
              </div>
            )
          }

          if (clarification) {
            return (
              <div key={turn.id} className="flex justify-start">
                <ClarificationCard
                  clarification={clarification}
                  answeredOptionId={answeredOptionId}
                  answeredByRetailer={answeredByRetailer}
                  onSelect={(optionId) => {
                    const label = clarification.options.find((o) => o.id === optionId)?.label ?? optionId
                    onSelectOption(turn.id, optionId, label)
                  }}
                  onSelectMultiple={(answersByRetailer) => {
                    const displayLabel = Object.entries(answersByRetailer)
                      .map(([retailer, label]) => `${formatRetailerName(retailer)}: ${label}`)
                      .join(', ')
                    onSelectMultipleOption(turn.id, answersByRetailer, displayLabel)
                  }}
                />
              </div>
            )
          }

          if (response.message) {
            // Covers both general_chat replies and the "you already have everything"
            // result (CP10 — no_ingredients_to_buy.py) — the latter also carries the
            // recipe's full original ingredient list, shown here so declining to buy
            // anything still leaves the user with a record of what the recipe needed.
            return (
              <div key={turn.id} className="flex flex-col gap-3">
                {response.recipe && (
                  <div className="flex justify-start">
                    <RecipeIngredientsView recipe={response.recipe} />
                  </div>
                )}
                <AssistantBubble>{response.message}</AssistantBubble>
              </div>
            )
          }

          // Once a specific retailer is chosen, never show the comparison again — only
          // that retailer's own cart-preparation result and its (already server-side
          // filtered, see finalize.py) warnings. Declining ("just show me this") leaves
          // chosen_retailer unset, so the comparison view below still applies there.
          if (response.chosen_retailer) {
            return (
              <div key={turn.id} className="flex flex-col gap-3">
                {response.retailer_cart_result && (
                  <div className="flex justify-start">
                    <RetailerCartResultView result={response.retailer_cart_result} />
                  </div>
                )}
                {response.warnings.length > 0 && (
                  <AssistantBubble>
                    <WarningsList warnings={response.warnings} />
                  </AssistantBubble>
                )}
                {!response.retailer_cart_result && response.warnings.length === 0 && (
                  <AssistantBubble>All done.</AssistantBubble>
                )}
              </div>
            )
          }

          // `carts` is `{}` (truthy in JS), not null, on non-cart responses like
          // general_chat — only render the comparison view when it actually has entries.
          if (response.carts && Object.keys(response.carts).length > 0) {
            return (
              <div key={turn.id} className="flex flex-col gap-3">
                <AssistantBubble>{leadText(response.status)}</AssistantBubble>
                {response.recipe && (
                  <div className="flex justify-start">
                    <RecipeIngredientsView recipe={response.recipe} />
                  </div>
                )}
                <div className="flex justify-start">
                  <RetailerComparison carts={response.carts} chosenRetailer={response.chosen_retailer} />
                </div>
                {response.warnings.length > 0 && (
                  <AssistantBubble>
                    <WarningsList warnings={response.warnings} />
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
