import { motion } from 'framer-motion'

function dotTransition(delay: number) {
  return {
    duration: 0.6,
    repeat: Infinity,
    repeatType: 'loop' as const,
    ease: 'easeInOut' as const,
    delay,
  }
}

export function TypingIndicator() {
  return (
    <div className="flex w-fit items-center gap-1 rounded-3xl rounded-bl-md bg-zinc-100 px-4 py-3">
      {[0, 0.15, 0.3].map((delay) => (
        <motion.span
          key={delay}
          className="h-2 w-2 rounded-full bg-zinc-400"
          animate={{ y: [0, -4, 0] }}
          transition={dotTransition(delay)}
        />
      ))}
    </div>
  )
}
