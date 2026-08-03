import { Check } from 'lucide-react'

interface OptionChipProps {
  label: string
  selected?: boolean
  disabled?: boolean
  onClick?: () => void
}

export function OptionChip({ label, selected, disabled, onClick }: OptionChipProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition disabled:cursor-default ${
        selected
          ? 'border-blue-400 bg-blue-50 text-blue-700'
          : 'border-zinc-200 bg-white text-zinc-700 hover:border-emerald-300 hover:text-emerald-700'
      } ${disabled && !selected ? 'opacity-40' : ''}`}
    >
      <Check className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}
