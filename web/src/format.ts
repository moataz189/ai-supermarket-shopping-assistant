const RETAILER_LABELS: Record<string, string> = {
  shufersal: 'Shufersal',
  rami_levy: 'Rami Levy',
}

export function formatRetailerName(retailer: string): string {
  return RETAILER_LABELS[retailer] ?? retailer
}

// Recipe-scaled amounts (e.g. 400 * 8/4) can land on values like 799.9999999999999 —
// trims that float noise to at most 2 decimal places without padding whole numbers with
// trailing zeros (400, not 400.00).
function formatNumber(value: number): string {
  return Number(value.toFixed(2)).toString()
}

/** Formats a recipe ingredient/cart quantity for display, e.g. (400, "g") -> "400 g",
 * (3, "large") -> "3 large", (0.5, "kg") -> "0.5 kg". `unit` is omitted (just the bare
 * number) when absent, since a plain grocery-list item has no recipe unit at all. */
export function formatQuantity(quantity: number, unit?: string | null): string {
  const amount = formatNumber(quantity)
  return unit ? `${amount} ${unit}` : amount
}
