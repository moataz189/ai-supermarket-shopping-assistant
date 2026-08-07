import { ChefHat } from 'lucide-react'
import type { RecipeInfo } from '@/api'
import { formatQuantity } from '@/format'

interface RecipeIngredientsViewProps {
  recipe: RecipeInfo
}

// Shown before/alongside the retailer comparison (spec: the user shouldn't have to infer
// a recipe's real quantities from the final cart) — the scaled amount actually returned
// by the Recipe MCP, not the original recipe's un-scaled one.
export function RecipeIngredientsView({ recipe }: RecipeIngredientsViewProps) {
  return (
    <div className="flex w-full max-w-3xl flex-col gap-3 rounded-3xl border border-zinc-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
          <ChefHat className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <p className="text-lg font-semibold text-zinc-900">{recipe.title ?? 'Ingredients'}</p>
          {recipe.servings != null && (
            <p className="text-sm text-zinc-500">Ingredients for {recipe.servings} servings</p>
          )}
        </div>
      </div>

      <ul className="space-y-1 text-sm text-zinc-600">
        {recipe.ingredients.map((ingredient) => (
          <li key={ingredient.name} className="flex items-center justify-between gap-3">
            <span className="truncate capitalize">{ingredient.name}</span>
            {ingredient.quantity != null && (
              <span className="shrink-0 font-medium text-zinc-900">
                {formatQuantity(ingredient.quantity, ingredient.unit)}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
