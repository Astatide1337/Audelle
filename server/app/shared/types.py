from dataclasses import dataclass, field


@dataclass
class Filters:
    year_range: tuple[int | None, int | None] | None = None
    # Used to build the search query text only — YouTube Music gives no reliable
    # per-track genre field, so this can't be enforced as a hard post-filter.
    genres: list[str] = field(default_factory=list)
    # Free-text hint (e.g. "korean", "spanish") — best-effort, folded into the query text.
    language: str | None = None
    min_views: int | None = None


@dataclass
class TrackCandidate:
    id: str
    name: str
    artists: list[str]
    year: int
    # Real YouTube view count — a genuine popularity signal (unlike iTunes, which had none).
    popularity: int
    watch_url: str
    album_art: str | None
    # Internal catalog relevance metadata; these fields are not part of the
    # public API response. A provider's ordered search result is stronger than
    # raw view count for explicit title/artist requests.
    search_rank: int = 0
    query_match: int = 0
    # Zero-based provider query variant. -1 is reserved for callers that build
    # candidates manually; those candidates are treated as exact-query results
    # for backwards-compatible selection behavior.
    search_variant: int = -1
    search_kind: str = ""
