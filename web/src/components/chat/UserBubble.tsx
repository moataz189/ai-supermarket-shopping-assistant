import { motion } from 'framer-motion'

export function UserBubble({ text }: { text: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex justify-end"
    >
      <div className="max-w-[80%] rounded-3xl rounded-br-md bg-emerald-600 px-4 py-2.5 text-white">{text}</div>
    </motion.div>
  )
}
