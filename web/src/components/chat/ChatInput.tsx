import { useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUp } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { useTypewriter } from '@/hooks/useTypewriter'

interface ChatInputProps {
  variant: 'hero' | 'bar'
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

const TYPEWRITER_EXAMPLES = ['Weekly shopping under ₪250', 'Shakshuka for 4', 'Milk and eggs']

export function ChatInput({ variant, onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState('')
  const typed = useTypewriter(TYPEWRITER_EXAMPLES)

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  const isHero = variant === 'hero'
  // The hero input's placeholder types itself out cycling through examples instead of a
  // static string — only when there's no explicit placeholder override and nothing typed
  // yet, so it never fights with real user input or the "bar" variant used mid-chat.
  const showTypewriter = isHero && !placeholder && value === ''

  return (
    <form
      onSubmit={handleSubmit}
      className={
        isHero
          ? 'mx-auto flex w-full max-w-2xl items-center gap-2 rounded-3xl border border-zinc-200 bg-white p-2 shadow-lg shadow-emerald-900/10'
          : 'mx-auto flex w-full max-w-3xl items-center gap-2 rounded-3xl border border-zinc-200 bg-white p-2 shadow-md'
      }
    >
      <div className="relative min-w-0 flex-1">
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={disabled}
          placeholder={
            showTypewriter ? '' : (placeholder ?? 'e.g. Weekly shopping under ₪250, Shakshuka for 4, Milk and eggs')
          }
          className={
            isHero
              ? 'h-12 rounded-2xl border-0 text-base shadow-none focus-visible:ring-0'
              : 'h-11 rounded-2xl border-0 shadow-none focus-visible:ring-0'
          }
        />
        {showTypewriter && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-base text-muted-foreground"
          >
            e.g. {typed}
            <span className="ml-0.5 inline-block h-4 w-px animate-pulse bg-zinc-400" />
          </span>
        )}
      </div>
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
      >
        <ArrowUp className="h-5 w-5" />
      </button>
    </form>
  )
}
