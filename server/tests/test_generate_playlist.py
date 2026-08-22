import pytest

from app.mood_parser.parse_vibe import QueryPlan
from app.playlist_service.generate_playlist import apply_filters, dedup_tracks, generate_playlist, select_seeded_tracks
from app.shared.types import Filters, TrackCandidate


def track(**overrides) -> TrackCandidate:
    defaults = dict(id="1", name="Test Track", artists=["Test Artist"], year=2020, popularity=1000, watch_url="https://x", album_art=None)
    defaults.update(overrides)
    return TrackCandidate(**defaults)


def test_apply_filters_excludes_outside_year_range():
    tracks = [track(id="a", year=2010), track(id="b", year=2020)]
    result = apply_filters(tracks, Filters(year_range=(2015, 2024)))
    assert [t.id for t in result] == ["b"]


def test_apply_filters_supports_one_sided_year_ranges():
    tracks = [track(id="old", year=2010), track(id="new", year=2020)]
    assert [t.id for t in apply_filters(tracks, Filters(year_range=(2015, None)))] == ["new"]
    assert [t.id for t in apply_filters(tracks, Filters(year_range=(None, 2015)))] == ["old"]


def test_apply_filters_excludes_tracks_with_unknown_year_when_year_is_constrained():
    tracks = [track(id="unknown", year=0), track(id="known", year=2010)]
    assert [t.id for t in apply_filters(tracks, Filters(year_range=(None, 2015)))] == ["known"]


def test_apply_filters_excludes_below_min_views():
    tracks = [track(id="a", popularity=100), track(id="b", popularity=100_000)]
    result = apply_filters(tracks, Filters(min_views=10_000))
    assert [t.id for t in result] == ["b"]


def test_apply_filters_passes_everything_with_no_filters():
    tracks = [track(id="a"), track(id="b")]
    assert len(apply_filters(tracks, Filters())) == 2


def test_dedup_collapses_same_name_and_artist():
    tracks = [
        track(id="1", name="Song", artists=["Artist"]),
        track(id="2", name="Song", artists=["Artist"]),
        track(id="3", name="Other Song", artists=["Artist"]),
    ]
    assert [t.id for t in dedup_tracks(tracks)] == ["1", "3"]


def test_dedup_is_case_insensitive():
    tracks = [track(id="1", name="Song", artists=["Artist"]), track(id="2", name="SONG", artists=["artist"])]
    assert len(dedup_tracks(tracks)) == 1


def test_seeded_selection_is_reproducible_but_explores_beyond_the_core():
    tracks = [
        track(id=f"track-{index}", name=f"Track {index}", popularity=10_000 - index)
        for index in range(40)
    ]

    first = select_seeded_tracks(tracks, limit=20, seed=123)
    replay = select_seeded_tracks(tracks, limit=20, seed=123)
    alternate = select_seeded_tracks(tracks, limit=20, seed=456)

    assert [item.id for item in first] == [item.id for item in replay]
    assert {item.id for item in first} != {item.id for item in alternate}
    assert [item.id for item in first[:3]] == ["track-0", "track-1", "track-2"]
    assert [item.popularity for item in first] == sorted((item.popularity for item in first), reverse=True)


@pytest.mark.asyncio
@pytest.mark.live
async def test_generate_playlist_live_respects_limit_and_filters_and_ranks_by_popularity():
    plan = QueryPlan(genre_seeds=["hip hop"], keyword_seeds=["workout", "gym"])
    playlist = await generate_playlist(plan, Filters(year_range=(1990, 2026)), 5)
    assert len(playlist.tracks) <= 5
    for t in playlist.tracks:
        assert 1990 <= t.year <= 2026
    popularities = [t.popularity for t in playlist.tracks]
    assert popularities == sorted(popularities, reverse=True)
