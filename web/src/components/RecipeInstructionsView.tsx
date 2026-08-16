import { ChefHat, Loader2 } from 'lucide-react'
import type { RecipeInfo } from '@/api'
import type { RecipeInstructionsState } from '@/types'

interface RecipeInstructionsViewProps {
  recipe: RecipeInfo
  instructions: RecipeInstructionsState | undefined
  onRequest: () => void
}

// Strips HTML tags from Spoonacular's plain `instructions` field for safe display as
// text — never rendered via dangerouslySetInnerHTML, since it's third-party content.
function stripHtml(html: string): string {
  return html
    .replace(/<\/(p|li|ol|ul)>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

// Offers to show, then displays, cooking instructions for the same Spoonacular recipe
// already selected earlier in the conversation — fetched statelessly via
// POST /recipe-instructions (app/api/routes/recipe.py), independent of the chat thread.
// Instructions always come from Spoonacular's own data, never invented here or by the LLM.
export function RecipeInstructionsView({ recipe, instructions, onRequest }: RecipeInstructionsViewProps) {
  if (recipe.id == null) return null

  const title = recipe.title ?? 'this recipe'

  if (!instructions) {
    return (
      <div className="flex w-full max-w-3xl flex-col gap-3 rounded-3xl border border-zinc-200 bg-white p-5">
        <p className="text-sm text-zinc-600">Would you like to see how to prepare {title}?</p>
        <button
          type="button"
          onClick={onRequest}
          className="w-fit rounded-full bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
        >
          Show me how
        </button>
      </div>
    )
  }

  if (instructions.status === 'loading') {
    return (
      <div className="flex w-full max-w-3xl items-center gap-2 rounded-3xl border border-zinc-200 bg-white p-5 text-sm text-zinc-500">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Fetching instructions…
      </div>
    )
  }

  if (instructions.status === 'error' || !instructions.data) {
    return (
      <div className="flex w-full max-w-3xl flex-col gap-1 rounded-3xl border border-zinc-200 bg-white p-5">
        <p className="text-sm text-zinc-500">Couldn't load instructions for {title} right now.</p>
      </div>
    )
  }

  const { steps, instructions: rawInstructions } = instructions.data
  const plainText = !steps?.length && rawInstructions ? stripHtml(rawInstructions) : null

  return (
    <div className="flex w-full max-w-3xl flex-col gap-3 rounded-3xl border border-zinc-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
          <ChefHat className="h-5 w-5" aria-hidden />
        </span>
        <p className="text-lg font-semibold text-zinc-900">How to prepare {title}</p>
      </div>

      {steps && steps.length > 0 && (
        <ol className="list-decimal space-y-2 pl-5 text-sm text-zinc-700">
          {steps.map((step) => (
            <li key={step.number}>{step.step}</li>
          ))}
        </ol>
      )}

      {plainText && <p className="whitespace-pre-line text-sm text-zinc-700">{plainText}</p>}

      {!steps?.length && !plainText && (
        <p className="text-sm text-zinc-500">No instructions available for this recipe.</p>
      )}
    </div>
  )
}
