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
      className="overflow-hidden pb-16 pt-16 text-center sm:pt-24"
      style={{
        // Subtle premium backdrop — soft radial-gradient glows in the existing emerald
        // palette, as plain CSS background layers (not separate absolutely-positioned/
        // blurred elements) so there's no z-index/stacking-context interaction with the
        // content below at all. Purely decorative, well behind the content by construction.
        backgroundImage: [
          'radial-gradient(480px circle at 50% 0%, rgba(16,185,129,0.18), transparent 70%)',
          'radial-gradient(420px circle at 8% 38%, rgba(110,231,183,0.22), transparent 70%)',
          'radial-gradient(420px circle at 92% 48%, rgba(94,234,212,0.20), transparent 70%)',
        ].join(', '),
      }}
    >
      <div className="mx-auto flex max-w-3xl flex-col items-center px-4">
        <GroceryIllustration />
        <h1 className="mt-6 text-4xl font-semibold tracking-tight text-zinc-900 sm:text-5xl">
          AI Supermarket Shopping Assistant
        </h1>
        <p className="mt-3 text-lg text-zinc-500">
          Describe your shopping list, recipe or budget. We&apos;ll compare Shufersal and Rami Levy and
          prepare the best shopping cart.
        </p>
        <SupportedRetailers />
        <div className="mt-6 w-full">
          <ChatInput variant="hero" onSend={onSend} disabled={disabled} />
          <PromptChips onSelect={onSend} disabled={disabled} />
        </div>
      </div>
    </motion.section>
  )
}
