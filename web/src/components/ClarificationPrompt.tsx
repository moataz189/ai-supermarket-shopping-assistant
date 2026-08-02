import type { Clarification } from '../api'
import { formatRetailerName } from '../format'

interface ClarificationPromptProps {
  clarification: Clarification
  onSelect: (optionId: string) => void
}

export function ClarificationPrompt({ clarification, onSelect }: ClarificationPromptProps) {
  const { question, options, availability_by_retailer } = clarification

  return (
    <div className="clarification">
      <p className="clarification-question">{question}</p>

      {availability_by_retailer && (
        <ul className="availability-by-retailer">
          {Object.entries(availability_by_retailer).map(([retailer, names]) => (
            <li key={retailer}>
              <strong>{formatRetailerName(retailer)}:</strong> {names.join(', ')}
            </li>
          ))}
        </ul>
      )}

      <div className="clarification-options">
        {options.map((option) => (
          <button key={option.id} type="button" onClick={() => onSelect(option.id)}>
            {option.label}
          </button>
        ))}
      </div>
    </div>
  )
}
