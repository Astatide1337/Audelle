export interface Filters {
  yearFrom?: number
  yearTo?: number
  genres: string[]
  language?: string
  minViews?: number
}

export interface MatchedAnchor {
  id: string
  similarity: number
}

export interface QueryPlan {
  genre_seeds: string[]
  keyword_seeds: string[]
  matched_anchors: MatchedAnchor[]
}

export interface Track {
  id: string
  name: string
  artists: string[]
  year: number
  popularity: number
  watch_url: string
  album_art: string | null
}

export interface PlaylistResponse {
  plan: QueryPlan
  tracks: Track[]
  seed: number
}
