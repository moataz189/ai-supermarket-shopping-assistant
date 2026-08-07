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

      {options.length === 0 ? (
        <p className="mt-2 text-sm text-zinc-500">Type your answer in the message box below.</p>
      ) : availability_by_retailer ? (
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
