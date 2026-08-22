import type { Filters, PlaylistResponse } from './types'

export class CatalogUnavailableError extends Error {}

export async function generatePlaylist(text: string, filters: Filters, limit = 20, seed?: number): Promise<PlaylistResponse> {
  const res = await fetch('/api/playlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      limit,
      filters: {
        year_from: filters.yearFrom,
        year_to: filters.yearTo,
        genres: filters.genres,
        language: filters.language,
        min_views: filters.minViews,
      },
      ...(seed === undefined ? {} : { seed }),
    }),
  })

  if (res.status === 503) {
    throw new CatalogUnavailableError('The catalog is briefly unavailable.')
  }
  if (!res.ok) {
    throw new Error(`Request failed (${res.status})`)
  }
  return res.json()
}
