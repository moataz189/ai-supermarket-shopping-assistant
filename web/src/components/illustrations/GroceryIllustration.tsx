import { Apple, Carrot, Milk, ShoppingCart } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'

const satellites = [
  { Icon: Apple, className: '-top-1 left-1 text-red-500', delay: 0 },
  { Icon: Carrot, className: 'bottom-1 -left-2 text-orange-500', delay: 0.4 },
  { Icon: Milk, className: 'top-1 -right-2 text-blue-400', delay: 0.8 },
]

export function GroceryIllustration() {
  const reduceMotion = useReducedMotion()

  return (
    <div className="relative mx-auto h-16 w-16 sm:h-20 sm:w-20">
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
        <ShoppingCart className="h-7 w-7 text-emerald-600 sm:h-8 sm:w-8" strokeWidth={1.5} />
      </motion.div>
      {satellites.map(({ Icon, className, delay }) => (
        <motion.div
          key={className}
          className={`absolute rounded-full bg-white p-1 shadow-sm ${className}`}
          animate={reduceMotion ? undefined : { y: [0, -6, 0] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut', delay }}
        >
          <Icon className="h-3 w-3" strokeWidth={1.5} />
        </motion.div>
      ))}
    </div>
  )
}
