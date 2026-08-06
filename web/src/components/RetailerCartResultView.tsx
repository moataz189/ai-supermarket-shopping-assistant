import { ShoppingCart, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { RetailerCartResult } from '@/api'
import { formatRetailerName } from '@/format'

interface RetailerCartResultViewProps {
  result: RetailerCartResult
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
            <li key={item.item_code} className="flex items-center justify-between gap-2">
              <span className="truncate">{item.name}</span>
              <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
                Added × {item.quantity_confirmed ?? '?'}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      {result.failed.length > 0 && (
        <ul className="space-y-1 text-sm text-zinc-500">
          {result.failed.map((item) => (
            <li key={item.item_code} className="flex items-center justify-between gap-2">
              <span className="truncate">{item.name}</span>
              <Badge variant="secondary" className="bg-red-100 text-red-700 hover:bg-red-100">
                {item.reason ?? item.status}
              </Badge>
            </li>
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
