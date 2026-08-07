import { motion } from 'framer-motion'
import { GroceryIllustration } from '@/components/illustrations/GroceryIllustration'
import { ChatInput } from '@/components/chat/ChatInput'
import { PromptChips } from '@/components/chat/PromptChips'
import { SupportedRetailers } from '@/components/layout/SupportedRetailers'

interface HeroProps {
  onSend: (text: string) => void
  disabled?: boolean
}

export function Hero({ onSend, disabled }: HeroProps) {
  return (
    <motion.section
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25, ease: 'easeInOut' }}
      className="mx-auto flex max-w-3xl flex-col items-center overflow-hidden px-4 pb-16 pt-16 text-center sm:pt-24"
    >
      <GroceryIllustration />
      <h1 className="mt-6 text-4xl font-semibold tracking-tight text-zinc-900 sm:text-5xl">
        AI Supermarket Shopping Assistant
      </h1>
      <p className="mt-3 text-lg text-zinc-500">
        Describe your shopping list, recipe or budget. We&apos;ll compare Shufersal and Rami Levy and
        prepare the best shopping cart.
      </p>
      <SupportedRetailers />
      <div className="mt-8 w-full">
        <ChatInput variant="hero" onSend={onSend} disabled={disabled} />
        <PromptChips onSelect={onSend} disabled={disabled} />
      </div>
    </motion.section>
  )
}
