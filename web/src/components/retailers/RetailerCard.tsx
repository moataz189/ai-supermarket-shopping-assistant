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
  const hasBudget = cart.budget != null
  // Only a genuine overshoot past the 10% tolerance is treated as "over budget" — a
  // total between the requested budget and allowed_max is shown as a subtle note
  // instead (see below), never a warning-style badge.
  const overAllowedMax = hasBudget && cart.allowed_max != null && cart.total > cart.allowed_max
  const overBudgetWithinTolerance = hasBudget && !overAllowedMax && cart.total > cart.budget!
  const hasSavings = cart.savings_vs_other != null && cart.savings_vs_other > 0
  // A ₪0.00 cart with missing items has nothing to compare, not a bargain — flagged
  // clearly instead of silently looking like just a cheap/empty cart. A budget-only
  // cart where nothing could fit at all (see no_items_fit_budget) gets its own message.
  const isIncomplete = cart.total === 0 && cart.missing_items.length > 0 && !cart.no_items_fit_budget

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

      {hasBudget && (
        <p className="mt-1 text-xs text-zinc-500">
          Requested budget: ₪{cart.budget!.toFixed(2)}
          {cart.allowed_max != null && <> · Allowed tolerance: up to ₪{cart.allowed_max.toFixed(2)}</>}
        </p>
      )}
      {overBudgetWithinTolerance && (
        <p className="mt-1 text-xs text-amber-600">
          ₪{(cart.total - cart.budget!).toFixed(2)} above your target, within the allowed 10% tolerance.
        </p>
      )}

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
        {hasBudget && (
          <Badge
            variant="secondary"
            className={
              overAllowedMax
                ? 'bg-red-100 text-red-700 hover:bg-red-100'
                : 'bg-emerald-100 text-emerald-700 hover:bg-emerald-100'
            }
          >
            {overAllowedMax ? `Over budget by ₪${cart.over_budget_by!.toFixed(2)}` : 'Under budget'}
          </Badge>
        )}
      </div>

      {cart.no_items_fit_budget && (
        <p className="mt-3 text-sm text-zinc-500">
          No suitable grocery items could be found within this budget.
        </p>
      )}

      <ul className="mt-4 space-y-1 text-sm text-zinc-600">
        {cart.items.map((line) => (
          <li key={line.item_code} className="flex justify-between gap-2">
            <span className="truncate">
              {line.product_name}{' '}
              {/* estimated_package_count (e.g. "× 2") takes priority when set — the
                  matched product is a whole package and this many is what will actually
                  be bought, so showing the raw requested weight/volume here (e.g.
                  "× 1000 g") would be confusing and wouldn't match subtotal's price.
                  Otherwise, the real requested amount (e.g. "800 g") when known — a
                  recipe ingredient, or a weekly-shop-profile item sized for its
                  household. The comparison-view qty otherwise shown here always stays 1
                  (see build_retailer_cart.py), which would misleadingly read as "× 1"
                  for an item that actually asked for more. */}
              {line.estimated_package_count != null
                ? `× ${line.estimated_package_count}`
                : line.requested_quantity != null
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
