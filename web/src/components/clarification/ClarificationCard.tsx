import { useState } from 'react'
import { OptionChip } from './OptionChip'
import type { Clarification } from '@/api'
import { formatRetailerName } from '@/format'

interface ClarificationCardProps {
  clarification: Clarification
  answeredOptionId?: string
  // One chosen option id per retailer, once answered — only relevant when
  // clarification.options_by_retailer is present (CP9 follow-up, 2026-08-08).
  answeredByRetailer?: Record<string, string>
  onSelect?: (optionId: string) => void
  onSelectMultiple?: (answersByRetailer: Record<string, string>) => void
}

export function ClarificationCard({
  clarification,
  answeredOptionId,
  answeredByRetailer,
  onSelect,
  onSelectMultiple,
}: ClarificationCardProps) {
  const { question, options, options_by_retailer } = clarification
  const answered = Boolean(answeredOptionId) || Boolean(answeredByRetailer)

  if (options_by_retailer) {
    return (
      <PerRetailerClarificationCard
        question={question}
        optionsByRetailer={options_by_retailer}
        answeredByRetailer={answeredByRetailer}
        onConfirm={onSelectMultiple}
      />
    )
  }

  return (
    <div className="w-full max-w-lg rounded-3xl border border-zinc-200 bg-white p-5">
      <p className="font-medium text-zinc-900">{question}</p>

      {options.length === 0 ? (
        <p className="mt-2 text-sm text-zinc-500">Type your answer in the message box below.</p>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          {options.map((option) => (
            <OptionChip
              key={option.id}
              label={option.label}
              price={option.price}
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

interface PerRetailerClarificationCardProps {
  question: string
  optionsByRetailer: NonNullable<Clarification['options_by_retailer']>
  answeredByRetailer?: Record<string, string>
  onConfirm?: (answersByRetailer: Record<string, string>) => void
}

// Independent per-retailer product disambiguation (CP9 follow-up, 2026-08-08): choosing a
// Shufersal option must never submit immediately or affect Rami Levy's own selection —
// each retailer group tracks its own pending pick locally, and a single Confirm submits
// all of them together only once every retailer shown here has one, so the two retailers
// end up with genuinely independent, comparable carts rather than one shared guess.
function PerRetailerClarificationCard({
  question,
  optionsByRetailer,
  answeredByRetailer,
  onConfirm,
}: PerRetailerClarificationCardProps) {
  const retailers = Object.keys(optionsByRetailer)
  const [pending, setPending] = useState<Record<string, string>>({})
  const answered = Boolean(answeredByRetailer)
  const selections = answered ? answeredByRetailer! : pending
  const allChosen = retailers.every((retailer) => selections[retailer])

  return (
    <div className="w-full max-w-lg rounded-3xl border border-zinc-200 bg-white p-5">
      <p className="font-medium text-zinc-900">{question}</p>
      <div className="mt-4 space-y-4">
        {retailers.map((retailer) => (
          <div key={retailer}>
            <p className="mb-2 text-sm font-medium text-zinc-500">{formatRetailerName(retailer)}</p>
            <div className="flex flex-wrap gap-2">
              {optionsByRetailer[retailer].map((option) => (
                <OptionChip
                  key={option.id}
                  label={option.label}
                  price={option.price}
                  selected={selections[retailer] === option.id}
                  disabled={answered}
                  onClick={
                    answered
                      ? undefined
                      : () => setPending((prev) => ({ ...prev, [retailer]: option.id }))
                  }
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      {!answered && (
        <button
          type="button"
          disabled={!allChosen}
          onClick={() => onConfirm?.(pending)}
          className="mt-4 rounded-full bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white transition disabled:cursor-default disabled:bg-zinc-200 disabled:text-zinc-400"
        >
          Confirm
        </button>
      )}
    </div>
  )
}
