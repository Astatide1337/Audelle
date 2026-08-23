import asyncio
import re
import time
from functools import lru_cache
from urllib.parse import urlparse

from ytmusicapi import YTMusic

from ..mood_parser.parse_vibe import QueryPlan
from ..shared.types import Filters, TrackCandidate
from .errors import CatalogUnavailableError

SEARCH_LIMIT = 30
# Keep enough candidates from each query variant for seeded exploration. The
# final playlist is still capped by the request limit, so this only affects
# which songs are eligible for selection.
CANDIDATE_POOL_LIMIT = 240
CANDIDATE_CACHE_TTL_SECONDS = 5 * 60
CANDIDATE_CACHE_MAX_ENTRIES = 128
# YouTube Music search returns plenty of hour-long "mix"/compilation videos
# alongside real songs; duration is a cheap, effective filter between them.
MIN_DURATION_SECONDS = 30
MAX_DURATION_SECONDS = 600
ALBUM_LOOKUP_CONCURRENCY = 5
YEAR_CACHE_MAX_ENTRIES = 4096
MAX_VIEW_COUNT = 10**15
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
THUMBNAIL_HOST_SUFFIX = ".googleusercontent.com"
_SEARCH_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SEARCH_STOP_WORDS = {
    "a", "an", "and", "by", "for", "from", "in", "me", "of", "on", "the", "to", "with",
}
_QUERY_FILLER_WORDS = _SEARCH_STOP_WORDS | {
    "music", "musics", "song", "songs", "track", "tracks", "playlist", "playlists",
    "listen", "listening", "please", "give", "make", "create", "some",
}
_STYLE_WORDS = {
    "ambient", "animated", "animation", "big", "cartoon", "cartoons", "chase", "cinematic",
    "classic", "classical", "comedy", "comic", "film", "folk", "funny", "instrumental",
    "jazz", "lofi", "lounge", "old", "orchestral", "piano", "score", "soundtrack", "swing",
    "symphonic", "vintage", "western",
}

_year_cache: dict[str, int] = {}
_candidate_cache: dict[tuple[str, ...], tuple[float, list[TrackCandidate]]] = {}


@lru_cache(maxsize=1)
def _client() -> YTMusic:
    return YTMusic()  # unauthenticated — search/browse are public, no login needed


def _build_search_variants(plan: QueryPlan, filters: Filters) -> list[tuple[str, str]]:
    """
    Build a small query portfolio rather than treating a named reference as a
    literal catalog lookup. The exact text remains first, followed by reference
    soundtrack/score queries and style-only queries when the user supplied
    explicit media or musical context (for example, ``old classical``). This
    lets a request for "Tom and Jerry" discover adjacent cartoon-score music
    without making every artist query look like a film-score request.
    """
    genre = (filters.genres[0] if filters.genres else None) or (plan.genre_seeds[0] if plan.genre_seeds else None)
    top_keywords = plan.keyword_seeds[:2]

    variants: list[tuple[str | None, str]] = [(plan.search_text, "exact")]
    query_words = re.findall(r"[A-Za-z0-9]+", plan.search_text)
    raw_tokens = {token.casefold() for token in query_words}
    reference_words = [
        token for token in query_words
        if token.casefold() not in _QUERY_FILLER_WORDS and token.casefold() not in _STYLE_WORDS
    ]
    reference = " ".join(reference_words)
    has_style_context = bool(raw_tokens & _STYLE_WORDS) or bool(filters.genres)
    classical_context = bool(raw_tokens & {"classical", "orchestral", "symphonic", "instrumental"})
    cartoon_context = bool(
        raw_tokens & {"cartoon", "cartoons", "animated", "animation", "comic", "comedy", "funny", "chase"}
    )
    vintage_context = bool(raw_tokens & {"old", "classic", "vintage"})
    jazz_context = bool(raw_tokens & {"jazz", "swing"})

    if reference and has_style_context:
        # These reference-led searches preserve the named subject while
        # widening the requested musical role beyond one famous theme.
        variants.append((f"{reference} soundtrack", "reference"))
        if classical_context:
            variants.append((f"{reference} orchestral score", "reference"))
        if cartoon_context or vintage_context:
            variants.append((f"{reference} cartoon chase music", "reference"))
        if jazz_context:
            variants.append((f"{reference} jazz swing", "reference"))

        # Style-only searches are deliberately explicit: they are the source
        # of adjacent scores and cues, not unrelated popular songs.
        if classical_context and (cartoon_context or vintage_context):
            variants.extend([
                ("classic cartoon chase music orchestral", "style"),
                ("old cartoon orchestral score", "style"),
                ("Scott Bradley Carl Stalling cartoon score", "style"),
            ])
        elif cartoon_context:
            variants.append(("cartoon chase music soundtrack", "style"))
        if jazz_context and (cartoon_context or vintage_context):
            variants.append(("cartoon soundtrack jazz swing", "style"))

    fallback_variants = [
        (" ".join(x for x in [*top_keywords, genre, filters.language] if x), "fallback"),
        (genre, "fallback"),
        (" ".join(top_keywords), "fallback"),
        (plan.keyword_seeds[0] if plan.keyword_seeds else None, "fallback"),
    ]
    # The style portfolio already includes its own broadening. Keep one
    # semantic fallback for reference-led requests so a burst of redundant
    # generic searches does not crowd the provider or dilute the pool.
    variants.extend(fallback_variants[:1] if reference and has_style_context else fallback_variants)

    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for value, kind in variants:
        if value and value.strip() and value.strip() not in seen:
            normalized = value.strip()
            seen.add(normalized)
            result.append((normalized, kind))
    return result


def build_search_term_candidates(plan: QueryPlan, filters: Filters) -> list[str]:
    return [term for term, _kind in _build_search_variants(plan, filters)]


def _parse_views(views: str | None) -> int:
    if not views:
        return 0
    match = re.match(r"^([\d.]+)\s*([KMB]?)$", views.strip().upper().replace(",", ""))
    if not match:
        return 0
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)]
    try:
        parsed = float(match.group(1))
    except ValueError:
        return 0
    return min(int(parsed * multiplier), MAX_VIEW_COUNT)


def _is_probably_real_song(result: dict) -> bool:
    video_id = result.get("videoId") if isinstance(result, dict) else None
    if not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id):
        return False
    title = result.get("title")
    artists = result.get("artists")
    if not isinstance(title, str) or not title.strip() or not isinstance(artists, list) or not artists:
        return False
    if any(not isinstance(artist, dict) or not isinstance(artist.get("name"), str) or not artist["name"].strip() for artist in artists):
        return False
    try:
        duration = float(result.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        return False
    return MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS


async def _search_once(term: str) -> list[dict]:
    try:
        return await asyncio.to_thread(_client().search, term, filter="songs", limit=SEARCH_LIMIT)
    except Exception as exc:  # ytmusicapi raises a mix of requests/internal errors
        raise CatalogUnavailableError(f"YouTube Music search failed: {exc}") from exc


def merge_search_results(result_sets: list[list[dict]], pool_limit: int = CANDIDATE_POOL_LIMIT) -> list[dict]:
    """Keep each provider query's order while building a de-duplicated pool.

    The first variant is the user's exact text and therefore the strongest
    relevance signal. Broader mood variants are appended only after it, rather
    than interleaved ahead of exact matches.
    """
    merged: list[dict] = []
    seen_ids: set[str] = set()
    for fallback_variant_index, results in enumerate(result_sets):
        for result_index, result in enumerate(results):
            video_id = result.get("videoId")
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            variant_index = int(result.get("_audelle_search_variant", fallback_variant_index))
            # Keep metadata out of the provider object and use a one-based rank
            # so an exact-query result remains distinguishable from an unset
            # rank used by callers that build a QueryPlan manually.
            merged.append({
                **result,
                "_audelle_search_rank": variant_index * SEARCH_LIMIT + result_index + 1,
                "_audelle_search_variant": variant_index,
            })
            if len(merged) >= pool_limit:
                return merged
    return merged


def _search_tokens(text: str) -> list[str]:
    return [token for token in _SEARCH_TOKEN_RE.findall(text.casefold()) if token not in _SEARCH_STOP_WORDS and len(token) > 1]


def _query_match_score(result: dict, search_text: str) -> int:
    """Score explicit words found in a result title/artist/album label."""
    query_tokens = _search_tokens(search_text)
    if not query_tokens:
        return 0
    artists = result.get("artists") or []
    artist_names = [artist.get("name", "") for artist in artists if isinstance(artist, dict)]
    album = result.get("album") if isinstance(result.get("album"), dict) else {}
    haystack = " ".join([result.get("title", ""), *artist_names, album.get("name", "")]).casefold()
    haystack_tokens = set(_SEARCH_TOKEN_RE.findall(haystack))
    score = sum(token in haystack_tokens for token in query_tokens)
    normalized_query = " ".join(query_tokens)
    if len(query_tokens) > 1 and normalized_query in " ".join(_SEARCH_TOKEN_RE.findall(haystack)):
        score += 2
    return score


def _cached_candidates(cache_key: tuple[str, ...]) -> list[TrackCandidate] | None:
    entry = _candidate_cache.get(cache_key)
    if entry is None:
        return None
    created_at, candidates = entry
    if time.monotonic() - created_at > CANDIDATE_CACHE_TTL_SECONDS:
        del _candidate_cache[cache_key]
        return None
    return list(candidates)


def _cache_candidates(cache_key: tuple[str, ...], candidates: list[TrackCandidate]) -> None:
    _candidate_cache[cache_key] = (time.monotonic(), list(candidates))
    if len(_candidate_cache) <= CANDIDATE_CACHE_MAX_ENTRIES:
        return
    oldest_key = min(_candidate_cache, key=lambda key: _candidate_cache[key][0])
    del _candidate_cache[oldest_key]


async def _lookup_year(album_id: str, sem: asyncio.Semaphore) -> int:
    if album_id in _year_cache:
        return _year_cache[album_id]
    async with sem:
        try:
            album = await asyncio.to_thread(_client().get_album, album_id)
        except Exception:
            # Do not make a transient provider failure permanent for this
            # process. A later request should be allowed to recover the year.
            return 0
    if not isinstance(album, dict):
        return 0
    try:
        year = int(album.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    if year > 0:
        _remember_year(album_id, year)
    return year


def _remember_year(album_id: str, year: int) -> None:
    _year_cache[album_id] = year
    if len(_year_cache) > YEAR_CACHE_MAX_ENTRIES:
        _year_cache.pop(next(iter(_year_cache)))


_THUMBNAIL_SIZE_RE = re.compile(r"=w\d+-h\d+")
THUMBNAIL_SIZE = 720


def _thumbnail_url(result: dict) -> str | None:
    thumbnails = result.get("thumbnails") or []
    if not thumbnails:
        return None
    last_thumbnail = thumbnails[-1]
    if not isinstance(last_thumbnail, dict):
        return None
    url = last_thumbnail.get("url")
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(THUMBNAIL_HOST_SUFFIX):
        return None
    # ytmusicapi returns googleusercontent URLs sized for tiny list-view thumbnails
    # (e.g. "=w120-h120-l90-rj"). That same URL param accepts any size, and we use
    # this image as a full-bleed background, so request it much larger up front.
    return _THUMBNAIL_SIZE_RE.sub(f"=w{THUMBNAIL_SIZE}-h{THUMBNAIL_SIZE}", url)


async def search_candidates(plan: QueryPlan, filters: Filters) -> list[TrackCandidate]:
    """
    Searches YouTube Music's public (unauthenticated) catalog for tracks matching
    the query plan and filters. Chosen over Spotify (Premium-gated as of Feb 2026)
    and Apple's iTunes Search API (literal word-matching, no popularity signal) —
    real search relevance, genuine view-count popularity, and no auth required for
    discovery. All progressively broader query variants are merged into a bounded
    pool so a fresh request seed can explore beyond one deterministic top slice.
    A short bounded snapshot cache keeps explicit seeds replayable while the
    third-party catalog is changing underneath us.
    """
    variant_specs = _build_search_variants(plan, filters)
    variants = [term for term, _kind in variant_specs]

    if not variants:
        return []
    cache_key = tuple(variant.casefold() for variant in variants)
    cached = _cached_candidates(cache_key)
    if cached is not None:
        return cached

    search_results = await asyncio.gather(*(_search_once(term) for term in variants), return_exceptions=True)
    valid_sets: list[list[dict]] = []
    errors: list[Exception] = []
    for variant_index, result in enumerate(search_results):
        if isinstance(result, Exception):
            errors.append(result)
            continue
        if not isinstance(result, list):
            errors.append(CatalogUnavailableError("YouTube Music returned an invalid search response"))
            continue
        valid_sets.append([
            {
                **r,
                "_audelle_search_variant": variant_index,
                "_audelle_search_kind": variant_specs[variant_index][1],
            }
            for r in result
            if isinstance(r, dict) and _is_probably_real_song(r)
        ][:SEARCH_LIMIT])

    # A partial catalog outage should not erase usable results from the other
    # variants. Only fail when every upstream query failed.
    if not valid_sets:
        if errors:
            raise errors[0]
        _cache_candidates(cache_key, [])
        return []

    raw_results = merge_search_results(valid_sets)

    if not raw_results:
        # Do not pin a transient partial outage as an empty snapshot; a later
        # request should be able to recover as soon as the catalog responds.
        if not errors:
            _cache_candidates(cache_key, [])
        return []

    album_ids = {
        r["album"]["id"]
        for r in raw_results
        if isinstance(r.get("album"), dict) and isinstance(r["album"].get("id"), str) and r["album"].get("id")
    }
    sem = asyncio.Semaphore(ALBUM_LOOKUP_CONCURRENCY)
    years = await asyncio.gather(*(_lookup_year(album_id, sem) for album_id in album_ids))
    years_by_album = dict(zip(album_ids, years))

    candidates: list[TrackCandidate] = []
    for r in raw_results:
        album_id = (r.get("album") or {}).get("id")
        candidates.append(
            TrackCandidate(
                id=r["videoId"],
                name=r["title"].strip()[:300],
                artists=[a["name"].strip()[:120] for a in r["artists"][:8]],
                year=years_by_album.get(album_id, 0),
                popularity=_parse_views(r.get("views")),
                watch_url=f"https://music.youtube.com/watch?v={r['videoId']}",
                album_art=_thumbnail_url(r),
                search_rank=int(r.get("_audelle_search_rank") or 0) if plan.search_text else 0,
                query_match=_query_match_score(r, plan.search_text) if plan.search_text else 0,
                search_variant=int(r.get("_audelle_search_variant") or 0) if plan.search_text else -1,
                search_kind=str(r.get("_audelle_search_kind") or "") if plan.search_text else "",
            )
        )
    _cache_candidates(cache_key, candidates)
    return list(candidates)
