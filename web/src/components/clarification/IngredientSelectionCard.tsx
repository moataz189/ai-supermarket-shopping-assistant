import { useState } from 'react'
import { ChefHat, Check } from 'lucide-react'
import type { Clarification } from '@/api'
import { formatQuantity } from '@/format'

interface IngredientSelectionCardProps {
  clarification: Clarification
  // The ingredient ids the user actually submitted, once answered.
  answeredIngredientIds?: string[]
  onConfirm?: (selectedIds: string[]) => void
}

// Recipe ingredient selection (CP10): every ingredient starts checked (spec — pressing
// Continue with no changes should buy everything), the user unchecks what they already
// have at home, and nothing is sent until they press Continue — no auto-continue on
// every click, unlike the flat ClarificationCard's single-choice chips.
export function IngredientSelectionCard({
  clarification,
  answeredIngredientIds,
  onConfirm,
}: IngredientSelectionCardProps) {
  const ingredients = clarification.ingredients ?? []
  const recipe = clarification.recipe
  const answered = Boolean(answeredIngredientIds)
  const [pending, setPending] = useState<Set<string>>(
    () => new Set(ingredients.filter((ingredient) => ingredient.selected).map((ingredient) => ingredient.id)),
  )
  const selectedIds = answered ? new Set(answeredIngredientIds) : pending

  function toggle(id: string) {
    if (answered) return
    setPending((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  return (
    <div className="w-full max-w-lg rounded-3xl border border-zinc-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
          <ChefHat className="h-5 w-5" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="truncate text-lg font-semibold text-zinc-900">{recipe?.title ?? 'Ingredients'}</p>
          {recipe?.servings != null && (
            <p className="text-sm text-zinc-500">Ingredients for {recipe.servings} servings</p>
          )}
        </div>
      </div>

      <ul className="mt-4 space-y-1">
        {ingredients.map((ingredient) => {
          const checked = selectedIds.has(ingredient.id)
          return (
            <li key={ingredient.id}>
              <label
                className={`flex items-center gap-3 rounded-2xl px-2 py-2 transition ${
                  answered ? '' : 'cursor-pointer hover:bg-zinc-50'
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={checked}
                  disabled={answered}
                  onChange={() => toggle(ingredient.id)}
                />
                <span
                  aria-hidden
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition ${
                    checked ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-zinc-300 bg-white'
                  } ${answered ? 'opacity-60' : ''}`}
                >
                  {checked && <Check className="h-3.5 w-3.5" />}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm text-zinc-800">{ingredient.display_name}</span>
                {ingredient.quantity != null && (
                  <span className="shrink-0 text-sm font-medium text-zinc-500">
                    {formatQuantity(ingredient.quantity, ingredient.unit)}
                  </span>
                )}
              </label>
            </li>
          )
        })}
      </ul>

      {!answered && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setPending(new Set(ingredients.map((ingredient) => ingredient.id)))}
            className="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 transition hover:border-emerald-300 hover:text-emerald-700"
          >
            Select all
          </button>
          <button
            type="button"
            onClick={() => setPending(new Set())}
            className="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 transition hover:border-emerald-300 hover:text-emerald-700"
          >
            Clear all
          </button>
          <button
            type="button"
            onClick={() => onConfirm?.(Array.from(pending))}
            className="ml-auto rounded-full bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700"
          >
            Continue
          </button>
        </div>
      )}
    </div>
  )
}
