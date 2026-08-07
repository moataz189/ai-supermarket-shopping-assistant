import { motion } from 'framer-motion'

const PROMPTS = [
  'Pasta for 4 people',
  'Weekly shopping under ₪250',
  'Gluten-free breakfast',
  'Chicken, rice and vegetables',
]

interface PromptChipsProps {
  onSelect: (prompt: string) => void
  disabled?: boolean
}

export function PromptChips({ onSelect, disabled }: PromptChipsProps) {
  return (
    <div className="mt-1.5 flex flex-col items-center">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Try one of these</p>
      <div className="mt-1 flex flex-wrap justify-center gap-1.5">
        {PROMPTS.map((prompt) => (
          <motion.button
            key={prompt}
            type="button"
            disabled={disabled}
            whileHover={disabled ? undefined : { y: -2 }}
            onClick={() => onSelect(prompt)}
            className="rounded-full border border-zinc-200 bg-white px-3.5 py-1 text-sm text-zinc-700 shadow-sm transition hover:border-emerald-300 hover:text-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {prompt}
          </motion.button>
        ))}
      </div>
    </div>
  )
}
