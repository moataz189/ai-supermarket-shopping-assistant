import { motion } from 'framer-motion'
import { RetailerCard } from './RetailerCard'
import type { ClarificationOption, RetailerCart } from '@/api'

interface RetailerComparisonProps {
  carts: Record<string, RetailerCart>
  chosenRetailer?: string | null
  options?: ClarificationOption[]
  answeredOptionId?: string
  onChoose?: (optionId: string) => void
}

export function RetailerComparison({
  carts,
  chosenRetailer,
  options,
  answeredOptionId,
  onChoose,
}: RetailerComparisonProps) {
  const entries = Object.entries(carts)
  const isInteractive = Boolean(onChoose) && !answeredOptionId
  const declineOption = options?.find((o) => o.id === 'decline')

  return (
    <div className="w-full max-w-3xl">
      <motion.div
        initial="hidden"
        animate="visible"
        variants={{ visible: { transition: { staggerChildren: 0.08 } } }}
        className="grid gap-4 sm:grid-cols-2"
      >
        {entries.map(([retailer, cart]) => {
          const option = options?.find((o) => o.id === retailer)
          return (
            <motion.div key={retailer} variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0 } }}>
              <RetailerCard
                retailer={retailer}
                cart={cart}
                selected={chosenRetailer === retailer || answeredOptionId === retailer}
                chooseLabel={option?.label}
                onChoose={isInteractive ? () => onChoose!(retailer) : undefined}
              />
            </motion.div>
          )
        })}
      </motion.div>

      {isInteractive && (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-xs text-blue-700">
          <span aria-hidden>ℹ️</span>
          <p>
            Prices shown include only the grocery items.
            <br />
            Delivery fees are not included and typically range between ₪30–₪40, depending on
            the retailer, delivery area, delivery time, promotions, and minimum order
            requirements.
          </p>
        </div>
      )}

      {isInteractive && declineOption && (
        <button
          type="button"
          onClick={() => onChoose!(declineOption.id)}
          className="mt-4 text-sm text-zinc-500 underline-offset-4 hover:text-zinc-700 hover:underline"
        >
          {declineOption.label}
        </button>
      )}
    </div>
  )
}
