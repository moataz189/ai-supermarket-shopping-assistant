import { Apple, Carrot, Croissant, Milk, ShoppingBasket } from 'lucide-react'

const ICONS = [
  { Icon: Apple, className: 'left-[3%] top-[10%] h-20 w-20 -rotate-12 opacity-[0.20] xl:h-24 xl:w-24' },
  { Icon: Carrot, className: 'left-[5%] top-[42%] h-24 w-24 rotate-12 opacity-[0.18] xl:h-28 xl:w-28' },
  { Icon: Milk, className: 'left-[2%] top-[75%] h-28 w-28 -rotate-6 opacity-[0.16] xl:h-32 xl:w-32' },
  { Icon: Croissant, className: 'right-[3%] top-[16%] h-24 w-24 rotate-6 opacity-[0.20] xl:h-28 xl:w-28' },
  { Icon: ShoppingBasket, className: 'right-[5%] top-[48%] h-28 w-28 -rotate-12 opacity-[0.18] xl:h-32 xl:w-32' },
  { Icon: Carrot, className: 'right-[2%] top-[78%] h-20 w-20 rotate-[18deg] opacity-[0.16] xl:h-24 xl:w-24' },
]

/** Purely decorative grocery icons in the wide side margins of the hero section —
 * flat/minimal (lucide's line style), low but consistently visible opacity (16-20%, larger
 * and brighter than the first pass per explicit follow-up feedback), hidden on narrow
 * screens where there's no side margin for them to live in anyway. Uses ordinary positive
 * z-index
 * stacking (this layer at z-0, the real content explicitly at z-10) rather than the
 * negative-z-index + overflow-hidden combination that silently failed to paint elsewhere
 * in this same section (see Hero.tsx) — real DOM elements, not a CSS background layer,
 * so that workaround doesn't apply here and this simpler, more standard approach is used
 * instead. A mask-image fades the whole layer toward the true left/right screen edges so
 * nothing looks abruptly cut off there. */
export function GroceryEdgeDecor() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 z-0 hidden overflow-hidden lg:block"
      style={{
        maskImage: 'linear-gradient(to right, transparent, black 12%, black 88%, transparent)',
        WebkitMaskImage: 'linear-gradient(to right, transparent, black 12%, black 88%, transparent)',
      }}
    >
      {ICONS.map(({ Icon, className }, i) => (
        <Icon key={i} className={`absolute text-emerald-900 ${className}`} strokeWidth={1.25} />
      ))}
    </div>
  )
}
