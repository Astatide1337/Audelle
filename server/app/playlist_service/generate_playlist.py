import random
import re
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


_TITLE_ANNOTATION_RE = re.compile(r"\([^)]*\)|\[[^]]*\]")
_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _title_family(name: str) -> str:
    """Collapse upload annotations so alternate copies of one theme compete."""
    without_annotations = _TITLE_ANNOTATION_RE.sub(" ", name.casefold())
    return " ".join(_TITLE_TOKEN_RE.findall(without_annotations))


def _is_theme_copy(name: str) -> bool:
    return bool(re.search(r"\b(?:main\s+)?theme\b|\bintro(?:duction)?\b", name.casefold()))


def _artist_key(track: TrackCandidate) -> str:
    return (track.artists[0] if track.artists else "").casefold()


def _search_variant(track: TrackCandidate) -> int:
    # Hand-built candidates from older callers have no variant metadata and
    # retain the historical exact-query behavior.
    return track.search_variant if track.search_variant >= 0 else 0


def _search_kind(track: TrackCandidate) -> str:
    return track.search_kind or ("exact" if _search_variant(track) == 0 else "fallback")


def _variant_priority(track: TrackCandidate) -> int:
    return {"exact": 0, "reference": 1, "style": 2, "fallback": 3}.get(_search_kind(track), 3)


def _selection_key(track: TrackCandidate) -> tuple:
    return (
        -track.query_match,
        _variant_priority(track),
        _search_variant(track),
        -track.popularity,
        track.search_rank,
        track.name.casefold(),
        track.id,
    )


def _select_diverse(
    tracks: list[TrackCandidate],
    limit: int,
    seed: int,
    *,
    round_robin_variants: bool = False,
) -> list[TrackCandidate]:
    """Seeded greedy selection with title-family, artist, and query diversity."""
    if limit <= 0 or not tracks:
        return []

    rng = random.Random(seed)
    remaining = list(tracks)
    selected: list[TrackCandidate] = []
    selected_families: set[str] = set()
    artist_counts: dict[str, int] = {}
    all_variant_order = sorted(
        {_search_variant(track) for track in remaining},
        key=lambda variant: (
            min(_variant_priority(track) for track in remaining if _search_variant(track) == variant),
            variant,
        ),
    )
    preferred_variant_order = [
        variant for variant in all_variant_order
        if any(
            _variant_priority(track) <= 2
            for track in remaining
            if _search_variant(track) == variant
        )
    ]
    if preferred_variant_order:
        offset = rng.randrange(len(preferred_variant_order))
        preferred_variant_order = preferred_variant_order[offset:] + preferred_variant_order[:offset]
    variant_cursor = 0

    def eligible(pool: list[TrackCandidate], *, enforce_family: bool, enforce_artist: bool) -> list[TrackCandidate]:
        return [
            track for track in pool
            if (not enforce_family or _title_family(track.name) not in selected_families)
            and (not enforce_artist or artist_counts.get(_artist_key(track), 0) < 2)
        ]

    while remaining and len(selected) < limit:
        candidate_pool = remaining
        if round_robin_variants and all_variant_order:
            # One candidate from each provider query variant per round keeps
            # style-only searches from being drowned out by the first variant.
            active_order = preferred_variant_order if any(
                _variant_priority(track) <= 2 for track in remaining
            ) else all_variant_order
            for _ in range(len(active_order)):
                variant = active_order[variant_cursor % len(active_order)]
                variant_cursor += 1
                bucket = [track for track in remaining if _search_variant(track) == variant]
                if bucket:
                    candidate_pool = bucket
                    break

        pool = eligible(candidate_pool, enforce_family=True, enforce_artist=True)
        if not pool:
            # Prefer an untouched title family from another variant before
            # relaxing diversity constraints inside the current bucket.
            pool = eligible(remaining, enforce_family=True, enforce_artist=True)
        if not pool:
            pool = eligible(candidate_pool, enforce_family=True, enforce_artist=False)
        if not pool:
            pool = eligible(candidate_pool, enforce_family=False, enforce_artist=False)
        if not pool:
            # The round-robin bucket may be exhausted by diversity constraints;
            # look across all remaining variants before giving up.
            pool = eligible(remaining, enforce_family=True, enforce_artist=True)
        if not pool:
            pool = eligible(remaining, enforce_family=False, enforce_artist=False)
        if not pool:
            break

        ranked = sorted(pool, key=_selection_key)
        # Preserve relevance bands while allowing a fresh request seed to pick
        # a different arrangement instead of repeating the first upload.
        best_match = ranked[0].query_match
        band = [track for track in ranked if track.query_match == best_match][:20]
        rng.shuffle(band)
        chosen = band[0]
        selected.append(chosen)
        remaining.remove(chosen)
        selected_families.add(_title_family(chosen.name))
        artist_counts[_artist_key(chosen)] = artist_counts.get(_artist_key(chosen), 0) + 1

    return selected


def select_seeded_tracks(tracks: list[TrackCandidate], limit: int, seed: int) -> list[TrackCandidate]:
    """Select a reproducible, relevant playlist without repeating one upload family."""
    relevance_mode = any(track.search_rank > 0 for track in tracks)
    if relevance_mode:
        exact = [track for track in tracks if _search_variant(track) == 0]
        broader = [track for track in tracks if _search_variant(track) > 0]
        # Keep one subject reference for a normal ten-track playlist, then let
        # the style/reference variants carry the playlist. For style-aware
        # requests, that reference comes from a soundtrack/score query rather
        # than the raw result set so one famous intro cannot dominate.
        reference_slots = min(limit, max(1, min(2, (limit + 9) // 10)))
        has_adjacent_variants = any(_search_kind(track) in {"reference", "style"} for track in broader)
        reference_pool = (
            [
                track for track in broader
                if _search_kind(track) == "reference" and not _is_theme_copy(track.name)
            ]
            or [track for track in exact if not _is_theme_copy(track.name)]
            if has_adjacent_variants
            else exact
        )
        safe_exact = [track for track in exact if not _is_theme_copy(track.name)]
        selected = _select_diverse(reference_pool or safe_exact or exact, reference_slots, seed)
        selected_families = {_title_family(item.name) for item in selected}
        broader_for_selection = (
            [track for track in broader if not _is_theme_copy(track.name)]
            if has_adjacent_variants
            else broader
        )
        selected_artist_counts: dict[str, int] = {}
        for item in selected:
            selected_artist_counts[_artist_key(item)] = selected_artist_counts.get(_artist_key(item), 0) + 1
        selected.extend(
            _select_diverse(
                [
                    track for track in broader_for_selection
                    if track.id not in {item.id for item in selected}
                    and _title_family(track.name) not in selected_families
                    and selected_artist_counts.get(_artist_key(track), 0) < 2
                ],
                limit - len(selected),
                seed ^ 0x5EED,
                round_robin_variants=True,
            )
        )
        if len(selected) < limit:
            selected_ids = {item.id for item in selected}
            selected_families = {_title_family(item.name) for item in selected}
            selected_artist_counts = {}
            for item in selected:
                selected_artist_counts[_artist_key(item)] = selected_artist_counts.get(_artist_key(item), 0) + 1
            fallback_exact = safe_exact if has_adjacent_variants else exact
            selected.extend(
                _select_diverse(
                    [
                        track for track in fallback_exact + broader_for_selection
                        if track.id not in selected_ids
                        and _title_family(track.name) not in selected_families
                        and selected_artist_counts.get(_artist_key(track), 0) < 2
                    ],
                    limit - len(selected),
                    seed ^ 0xD1CE,
                )
            )
        return selected[:limit]

    ranked = sorted(tracks, key=lambda track: (-track.popularity, track.name.casefold(), track.id))
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
