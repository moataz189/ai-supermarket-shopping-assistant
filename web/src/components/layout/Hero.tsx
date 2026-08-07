import { useCallback, useRef } from 'react'
import type { CSSProperties, MouseEvent } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { GroceryIllustration } from '@/components/illustrations/GroceryIllustration'
import { ChatInput } from '@/components/chat/ChatInput'
import { PromptChips } from '@/components/chat/PromptChips'
import { SupportedRetailers } from '@/components/layout/SupportedRetailers'
import { FeatureHighlights } from '@/components/layout/FeatureHighlights'
import { GroceryEdgeDecor } from '@/components/layout/GroceryEdgeDecor'

interface HeroProps {
  onSend: (text: string) => void
  disabled?: boolean
}

const itemVariants = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0 },
}

export function Hero({ onSend, disabled }: HeroProps) {
  const sectionRef = useRef<HTMLElement>(null)
  const reduceMotion = useReducedMotion()

  // Mouse-tracking spotlight: updates CSS custom properties directly on the DOM node
  // (not React state) so it never re-renders on every mousemove — just a 4th layer in the
  // same backgroundImage stack that already renders reliably (see the other three
  // gradients below), positioned via --spot-x/--spot-y.
  const handleMouseMove = useCallback(
    (e: MouseEvent<HTMLElement>) => {
      if (reduceMotion) return
      const el = sectionRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const x = ((e.clientX - rect.left) / rect.width) * 100
      const y = ((e.clientY - rect.top) / rect.height) * 100
      el.style.setProperty('--spot-x', `${x}%`)
      el.style.setProperty('--spot-y', `${y}%`)
    },
    [reduceMotion],
  )

  return (
    <motion.section
      ref={sectionRef}
      onMouseMove={handleMouseMove}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25, ease: 'easeInOut' }}
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: 0.12, delayChildren: 0.05 } } }}
      className="relative overflow-hidden pb-6 pt-8 text-center sm:pt-10"
      style={
        {
          // Subtle premium backdrop — plain CSS background layers on the section itself
          // (not separate absolutely-positioned/blurred elements) so there's no z-index/
          // stacking-context interaction with the content below at all — confirmed live
          // that approach silently fails to paint in this exact overflow-hidden +
          // framer-motion combination. Deliberately asymmetric (one bigger/stronger glow,
          // one smaller/softer) rather than evenly matched circles, plus a 4th spotlight
          // layer that follows the cursor via --spot-x/--spot-y (falls back to a fixed
          // point, and is never updated at all, when the user prefers reduced motion).
          backgroundImage: [
            'radial-gradient(600px circle at var(--spot-x, 50%) var(--spot-y, 10%), rgba(16,185,129,0.16), transparent 60%)',
            'radial-gradient(520px circle at 46% 0%, rgba(16,185,129,0.20), transparent 70%)',
            'radial-gradient(460px circle at 6% 42%, rgba(110,231,183,0.26), transparent 70%)',
            'radial-gradient(340px circle at 94% 30%, rgba(94,234,212,0.16), transparent 70%)',
          ].join(', '),
        } as CSSProperties
      }
    >
      <GroceryEdgeDecor />
      <div className="relative z-10 mx-auto flex max-w-3xl flex-col items-center px-4">
        <motion.div variants={itemVariants}>
          <GroceryIllustration />
        </motion.div>
        <motion.div
          variants={itemVariants}
          className="mt-2 inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700"
        >
          <span aria-hidden>🛒</span>
          You choose what to buy. I&apos;ll build the cart.
        </motion.div>
        <motion.h1
          variants={itemVariants}
          className="animate-gradient-shift mt-2 bg-gradient-to-r from-zinc-900 via-emerald-700 to-zinc-900 bg-clip-text text-4xl font-semibold tracking-tight text-transparent sm:text-5xl"
        >
          AI Supermarket Shopping Assistant
        </motion.h1>
        <motion.p variants={itemVariants} className="mt-1.5 text-lg text-zinc-500">
          Describe your shopping list, recipe or budget. We&apos;ll compare Shufersal and Rami Levy and
          prepare the best shopping cart.
        </motion.p>
        <motion.div variants={itemVariants}>
          <SupportedRetailers />
        </motion.div>
        <motion.div variants={itemVariants} className="mt-2 w-full">
          <ChatInput variant="hero" onSend={onSend} disabled={disabled} />
          <PromptChips onSelect={onSend} disabled={disabled} />
        </motion.div>
        <motion.div variants={itemVariants} className="w-full">
          <FeatureHighlights />
        </motion.div>
      </div>
    </motion.section>
  )
}
