import random
import secrets
from dataclasses import dataclass, field

from ..catalog_service.search_candidates import search_candidates
from ..mood_parser.parse_vibe import QueryPlan
from ..shared.types import Filters, TrackCandidate


@dataclass
class Playlist:
    tracks: list[TrackCandidate] = field(default_factory=list)
    seed: int = 0


def apply_filters(tracks: list[TrackCandidate], filters: Filters) -> list[TrackCandidate]:
    """Year and view-count are enforced exactly; genre/language stay query-text-only (see catalog_service)."""
    result = []
    for t in tracks:
        if filters.year_range:
            year_from, year_to = filters.year_range
            # A missing catalog year is represented as zero. It cannot satisfy
            # an explicit year constraint, including an upper-bound-only one.
            if t.year <= 0 or (year_from is not None and t.year < year_from) or (year_to is not None and t.year > year_to):
                continue
        if filters.min_views is not None and t.popularity < filters.min_views:
            continue
        result.append(t)
    return result


def dedup_tracks(tracks: list[TrackCandidate]) -> list[TrackCandidate]:
    """Dedups by name+primary-artist rather than id — the catalog often returns the
    same song multiple times (official upload, lyric video, topic channel, etc.)."""
    seen: set[str] = set()
    result = []
    for t in tracks:
        key = f"{t.name.lower()}::{(t.artists[0] if t.artists else '').lower()}"
        if key in seen:
            continue
        seen.add(key)
        result.append(t)
    return result


def select_seeded_tracks(tracks: list[TrackCandidate], limit: int, seed: int) -> list[TrackCandidate]:
    """Keep a small relevance core, then sample the rest from the candidate pool.

    A stable seed makes a result reproducible when supplied, while the default
    request path generates a fresh seed. Sorting the selected tracks by the
    existing popularity signal keeps the player readable without collapsing the
    selection back to the same deterministic top slice.
    """
    ranked = sorted(
        tracks,
        key=lambda track: (-track.popularity, track.name.casefold(), track.id),
    )
    if len(ranked) <= limit:
        return ranked

    core_count = min(3, limit)
    core = ranked[:core_count]
    exploration = ranked[core_count:]
    random.Random(seed).shuffle(exploration)
    selected = core + exploration[: limit - core_count]
    return sorted(selected, key=lambda track: (-track.popularity, track.name.casefold(), track.id))


async def generate_playlist(plan: QueryPlan, filters: Filters, limit: int, seed: int | None = None) -> Playlist:
    """
    Orchestrates catalog search -> hard filters -> dedup -> seeded exploration
    selection. Unlike the iTunes-backed version, YouTube Music gives a genuine
    popularity signal, so the candidate pool is ranked by view count before the
    seed keeps a small relevance core and samples the remaining slots. This pushes
    content-mill/algorithmic uploads (common in YouTube's results for niche vibe
    queries) below legitimately known tracks without returning the same top slice.

    Known tradeoff: if filters are aggressive relative to the matched vibe, this
    can legitimately return fewer than `limit` tracks rather than padding with
    worse matches.
    """
    # Keep the generated value exact when it crosses the browser JSON boundary.
    request_seed = seed if seed is not None else secrets.randbelow(2**53)
    candidates = await search_candidates(plan, filters)
    filtered = apply_filters(candidates, filters)
    deduped = dedup_tracks(filtered)
    return Playlist(tracks=select_seeded_tracks(deduped, limit, request_seed), seed=request_seed)
