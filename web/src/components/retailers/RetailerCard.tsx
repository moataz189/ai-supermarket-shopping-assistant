import { Store } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { RetailerCart } from '@/api'
import { formatQuantity, formatRetailerName } from '@/format'

interface RetailerCardProps {
  retailer: string
  cart: RetailerCart
  selected?: boolean
  onChoose?: () => void
  chooseLabel?: string
}

export function RetailerCard({ retailer, cart, selected, onChoose, chooseLabel }: RetailerCardProps) {
  const name = formatRetailerName(retailer)
  const overBudget = cart.over_budget_by != null
  const hasSavings = cart.savings_vs_other != null && cart.savings_vs_other > 0
  // A ₪0.00 cart with missing items has nothing to compare, not a bargain — flagged
  // clearly instead of silently looking like just a cheap/empty cart.
  const isIncomplete = cart.total === 0 && cart.missing_items.length > 0

  return (
    <div
      className={`flex flex-col rounded-3xl border bg-white p-5 transition ${
        selected ? 'border-blue-400 ring-2 ring-blue-200' : 'border-zinc-200'
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100 text-zinc-500">
          <Store className="h-5 w-5" aria-hidden />
        </span>
        <span className="text-lg font-semibold text-zinc-900">{name}</span>
        {selected && (
          <Badge variant="secondary" className="ml-auto bg-blue-100 text-blue-700 hover:bg-blue-100">
            Selected
          </Badge>
        )}
      </div>

      <p className="mt-4 text-3xl font-bold text-zinc-900">₪{cart.total.toFixed(2)}</p>

      <div className="mt-2 flex flex-wrap gap-2">
        {hasSavings && (
          <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
            Save ₪{cart.savings_vs_other!.toFixed(2)}
          </Badge>
        )}
        {isIncomplete && (
          <Badge variant="secondary" className="bg-amber-100 text-amber-800 hover:bg-amber-100">
            Incomplete cart
          </Badge>
        )}
        {cart.budget != null && (
          <Badge
            variant="secondary"
            className={
              overBudget
                ? 'bg-red-100 text-red-700 hover:bg-red-100'
                : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-100'
            }
          >
            {overBudget ? `Over budget by ₪${cart.over_budget_by!.toFixed(2)}` : 'Under budget'}
          </Badge>
        )}
      </div>

      <ul className="mt-4 space-y-1 text-sm text-zinc-600">
        {cart.items.map((line) => (
          <li key={line.item_code} className="flex justify-between gap-2">
            <span className="truncate">
              {line.product_name}{' '}
              {/* The real requested amount (e.g. "800 g") when known — a recipe
                  ingredient, or a weekly-shop-profile item sized for its household. The
                  comparison-view qty otherwise shown here always stays 1 (see
                  build_retailer_cart.py), which would misleadingly read as "× 1" for an
                  item that actually asked for more. */}
              {line.requested_quantity != null
                ? `× ${formatQuantity(line.requested_quantity, line.requested_unit)}`
                : `× ${line.qty}`}
            </span>
            <span className="shrink-0 text-zinc-900">₪{line.subtotal.toFixed(2)}</span>
          </li>
        ))}
      </ul>

      {cart.missing_items.length > 0 && (
        <p className="mt-3 text-sm text-zinc-500">
          <span className="font-medium text-zinc-700">Missing: </span>
          {cart.missing_items.map((item) => String(item.name)).join(', ')}
        </p>
      )}

      {cart.trade_off_suggestions.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-zinc-500">
          {cart.trade_off_suggestions.map((s, i) => (
            <li key={i}>
              Swap {String(s.current_choice)} for {String(s.suggested_choice)} to save ₪
              {Number(s.savings).toFixed(2)}
            </li>
          ))}
        </ul>
      )}

      {onChoose && (
        <button
          type="button"
          onClick={onChoose}
          className="mt-4 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-emerald-700"
        >
          {chooseLabel ?? `Choose ${name}`}
        </button>
      )}
    </div>
  )
}
