const RETAILER_LABELS: Record<string, string> = {
  shufersal: 'Shufersal',
  rami_levy: 'Rami Levy',
}

export function formatRetailerName(retailer: string): string {
  return RETAILER_LABELS[retailer] ?? retailer
}
