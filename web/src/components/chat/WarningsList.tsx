import { formatRetailerName } from '@/format'

interface WarningsListProps {
  warnings: Record<string, unknown>[]
}

function itemLabel(item: unknown): string {
  if (typeof item !== 'object' || item === null) return String(item)
  const { name, reason } = item as { name?: unknown; reason?: unknown }
  const label = typeof name === 'string' ? name : String(name)
  return reason === 'dietary_conflict' ? `${label} (dietary conflict)` : label
}

function formatWarning(warning: Record<string, unknown>): string {
  const { code } = warning
  if (code === 'product_not_found') {
    const retailer = typeof warning.retailer === 'string' ? formatRetailerName(warning.retailer) : 'this retailer'
    const items = Array.isArray(warning.items) ? warning.items.map(itemLabel) : []
    return items.length > 0 ? `Missing from ${retailer}: ${items.join(', ')}` : `Some items were missing from ${retailer}.`
  }
  if (code === 'budget_exceeded') {
    const retailer = typeof warning.retailer === 'string' ? formatRetailerName(warning.retailer) : 'This retailer'
    const overBy = Number(warning.over_budget_by)
    return `${retailer} is ₪${overBy.toFixed(2)} over budget.`
  }
  if (code === 'recipe_not_found') {
    return `No recipe found for "${String(warning.query)}".`
  }
  // Unrecognized codes fall back to a readable-ish dump rather than a crash — keeps this
  // list future-proof against a warning shape this component doesn't know about yet.
  return JSON.stringify(warning)
}

export function WarningsList({ warnings }: WarningsListProps) {
  if (warnings.length === 0) return null

  return (
    <ul className="list-disc space-y-1 pl-4 text-sm">
      {warnings.map((warning, i) => (
        <li key={i}>{formatWarning(warning)}</li>
      ))}
    </ul>
  )
}
