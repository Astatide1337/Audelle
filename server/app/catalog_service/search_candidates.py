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
CANDIDATE_POOL_LIMIT = 120
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

_year_cache: dict[str, int] = {}
_candidate_cache: dict[tuple[str, ...], tuple[float, list[TrackCandidate]]] = {}


@lru_cache(maxsize=1)
def _client() -> YTMusic:
    return YTMusic()  # unauthenticated — search/browse are public, no login needed


def build_search_term_candidates(plan: QueryPlan, filters: Filters) -> list[str]:
    """
    Progressively broader query variants, same fallback strategy as the iTunes
    version: full term first, then genre-led, then just the strongest keyword.
    """
    genre = (filters.genres[0] if filters.genres else None) or (plan.genre_seeds[0] if plan.genre_seeds else None)
    top_keywords = plan.keyword_seeds[:2]

    variants = [
        " ".join(x for x in [*top_keywords, genre, filters.language] if x),
        genre,
        " ".join(top_keywords),
        plan.keyword_seeds[0] if plan.keyword_seeds else None,
    ]

    seen: list[str] = []
    for v in variants:
        if v and v.strip() and v.strip() not in seen:
            seen.append(v.strip())
    return seen


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
    """Interleave query variants into one de-duplicated exploration pool.

    The first variant is the most specific query, but letting it fill the pool
    before considering broader variants makes repeated prompts converge on the
    same top slice. Round-robin interleaving preserves relevance while giving
    the seeded selector meaningful alternatives.
    """
    merged: list[dict] = []
    seen_ids: set[str] = set()
    for position in range(SEARCH_LIMIT):
        for results in result_sets:
            if position >= len(results):
                continue
            result = results[position]
            video_id = result.get("videoId")
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            merged.append(result)
            if len(merged) >= pool_limit:
                return merged
    return merged


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
    variants = build_search_term_candidates(plan, filters)

    if not variants:
        return []
    cache_key = tuple(variant.casefold() for variant in variants)
    cached = _cached_candidates(cache_key)
    if cached is not None:
        return cached

    search_results = await asyncio.gather(*(_search_once(term) for term in variants), return_exceptions=True)
    valid_sets: list[list[dict]] = []
    errors: list[Exception] = []
    for result in search_results:
        if isinstance(result, Exception):
            errors.append(result)
            continue
        if not isinstance(result, list):
            errors.append(CatalogUnavailableError("YouTube Music returned an invalid search response"))
            continue
        valid_sets.append([
            r for r in result
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
            )
        )
    _cache_candidates(cache_key, candidates)
    return list(candidates)
