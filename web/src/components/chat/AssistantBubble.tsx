import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

export function AssistantBubble({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex justify-start"
    >
      <div className="max-w-[80%] rounded-3xl rounded-bl-md bg-zinc-100 px-4 py-2.5 text-zinc-800">{children}</div>
    </motion.div>
  )
}
