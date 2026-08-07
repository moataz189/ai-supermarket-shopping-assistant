import { Apple, Carrot, Milk, ShoppingCart } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'

const satellites = [
  { Icon: Apple, className: 'top-1 left-2 text-red-500', delay: 0 },
  { Icon: Carrot, className: 'bottom-4 left-0 text-orange-500', delay: 0.4 },
  { Icon: Milk, className: 'top-4 right-0 text-blue-400', delay: 0.8 },
]

export function GroceryIllustration() {
  const reduceMotion = useReducedMotion()

  return (
    <div className="relative mx-auto h-40 w-40 sm:h-48 sm:w-48">
      <motion.div
        className="absolute inset-0 rounded-full bg-emerald-100"
        animate={reduceMotion ? undefined : { scale: [1, 1.04, 1] }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        className="absolute inset-0 flex items-center justify-center"
        animate={reduceMotion ? undefined : { y: [0, -8, 0] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
      >
        <ShoppingCart className="h-16 w-16 text-emerald-600" strokeWidth={1.5} />
      </motion.div>
      {satellites.map(({ Icon, className, delay }) => (
        <motion.div
          key={className}
          className={`absolute rounded-full bg-white p-2 shadow-sm ${className}`}
          animate={reduceMotion ? undefined : { y: [0, -6, 0] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut', delay }}
        >
          <Icon className="h-5 w-5" strokeWidth={1.5} />
        </motion.div>
      ))}
    </div>
  )
}
