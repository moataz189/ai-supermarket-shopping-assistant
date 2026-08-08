import { ShoppingCart, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { RetailerCartItemResult, RetailerCartResult } from '@/api'
import { formatQuantity, formatRetailerName } from '@/format'

interface RetailerCartResultViewProps {
  result: RetailerCartResult
}

function AddedItem({ item }: { item: RetailerCartItemResult }) {
  // requested_quantity is set for any item with a real requested amount — a recipe
  // ingredient, or a weekly-shop-profile item sized for that profile's household (e.g.
  // 0.5 kg tomatoes for one person, 1 kg for a family). Shows what was actually asked
  // for alongside what ended up in the cart — e.g. a retailer's own weight increment can
  // round "400 g" up to "0.5 kg"; this is a successful, expected adjustment, not an
  // error, so it's shown as plain detail rather than a warning even when the two differ.
  if (item.requested_quantity != null) {
    return (
      <li className="flex items-center justify-between gap-2">
        <span className="truncate">{item.name}</span>
        <span className="shrink-0 text-right text-xs text-zinc-500">
          <span className="block">Requested: {formatQuantity(item.requested_quantity, item.requested_unit)}</span>
          <span className="block font-medium text-emerald-700">
            Added to cart: {formatQuantity(item.cart_quantity ?? item.quantity_confirmed ?? 0, item.cart_unit)}
          </span>
        </span>
      </li>
    )
  }

  return (
    <li className="flex items-center justify-between gap-2">
      <span className="truncate">{item.name}</span>
      <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
        Added × {item.quantity_confirmed ?? '?'}
      </Badge>
    </li>
  )
}

function FailedItem({ item }: { item: RetailerCartItemResult }) {
  // A structured "we couldn't determine a safe conversion" result (e.g. recipe asked
  // for "2 units" of something this retailer only sells by weight) — deliberately not
  // styled as a hard red error, since nothing was guessed wrong: the system correctly
  // declined to invent a conversion, and the user may just need to add this one by hand.
  if (item.status === 'quantity_conversion_required') {
    return (
      <li className="flex items-center justify-between gap-2">
        <span className="truncate">{item.name}</span>
        <Badge variant="secondary" className="bg-amber-100 text-amber-800 hover:bg-amber-100">
          Needs manual check — requested {formatQuantity(item.requested_quantity ?? 0, item.requested_unit)}
        </Badge>
      </li>
    )
  }

  return (
    <li className="flex items-center justify-between gap-2">
      <span className="truncate">{item.name}</span>
      <Badge variant="secondary" className="bg-red-100 text-red-700 hover:bg-red-100">
        {item.reason ?? item.status}
      </Badge>
    </li>
  )
}

export function RetailerCartResultView({ result }: RetailerCartResultViewProps) {
  const name = formatRetailerName(result.retailer)

  return (
    <div className="flex w-full max-w-3xl flex-col gap-3 rounded-3xl border border-zinc-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100 text-zinc-500">
          <ShoppingCart className="h-5 w-5" aria-hidden />
        </span>
        <span className="text-lg font-semibold text-zinc-900">{name} cart</span>
      </div>

      {result.blocked && (
        <div className="flex items-start gap-2 rounded-2xl bg-amber-50 p-3 text-sm text-amber-800">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>This site blocked automation: {result.blocked_reason}</span>
        </div>
      )}

      {result.added.length > 0 && (
        <ul className="space-y-1 text-sm text-zinc-600">
          {result.added.map((item) => (
            <AddedItem key={item.item_code} item={item} />
          ))}
        </ul>
      )}

      {result.failed.length > 0 && (
        <ul className="space-y-1 text-sm text-zinc-500">
          {result.failed.map((item) => (
            <FailedItem key={item.item_code} item={item} />
          ))}
        </ul>
      )}

      {result.cart_url && (
        <a
          href={result.cart_url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 text-sm font-medium text-blue-600 underline-offset-4 hover:underline"
        >
          Open cart on {name}
        </a>
      )}

      {result.added.length > 0 && result.cart_url && (
        <p className="text-xs text-zinc-400">
          Your {name} cart was updated. If your currently open {name} session still shows
          an empty cart, sign out and sign back in to refresh the account cart.
        </p>
      )}
    </div>
  )
}
