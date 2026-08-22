const compactFormatter = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

export function formatPlays(views: number): string {
  if (views <= 0) return ''
  return `${compactFormatter.format(views)} plays`
}
