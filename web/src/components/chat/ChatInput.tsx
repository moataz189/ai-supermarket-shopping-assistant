import { useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUp } from 'lucide-react'
import { Input } from '@/components/ui/input'

interface ChatInputProps {
  variant: 'hero' | 'bar'
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({ variant, onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  const isHero = variant === 'hero'

  return (
    <form
      onSubmit={handleSubmit}
      className={
        isHero
          ? 'mx-auto flex w-full max-w-2xl items-center gap-2 rounded-3xl border border-zinc-200 bg-white p-2 shadow-lg shadow-zinc-200/50'
          : 'mx-auto flex w-full max-w-3xl items-center gap-2 rounded-3xl border border-zinc-200 bg-white p-2 shadow-md'
      }
    >
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        placeholder={placeholder ?? 'e.g. Weekly shopping under ₪250, Shakshuka for 4, Milk and eggs'}
        className={
          isHero
            ? 'h-12 flex-1 rounded-2xl border-0 text-base shadow-none focus-visible:ring-0'
            : 'h-11 flex-1 rounded-2xl border-0 shadow-none focus-visible:ring-0'
        }
      />
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
