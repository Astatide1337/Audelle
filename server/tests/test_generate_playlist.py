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


def test_seeded_selection_keeps_explicit_query_matches_ahead_of_popularity():
    tracks = [
        track(id="generic", name="Young and Beautiful", popularity=900_000_000, search_rank=1, query_match=0),
        track(id="specific", name="Tom and Jerry Main Theme", popularity=10_000, search_rank=2, query_match=2),
    ]

    selected = select_seeded_tracks(tracks, limit=1, seed=123)

    assert [item.id for item in selected] == ["specific"]


def test_seeded_relevance_exploration_does_not_drop_into_low_match_results():
    tracks = [
        track(id="exact-a", name="Tom and Jerry Theme A", search_rank=1, query_match=3),
        track(id="exact-b", name="Tom and Jerry Theme B", search_rank=2, query_match=3),
        track(id="match-a", name="Tom and Jerry Theme C", search_rank=3, query_match=2),
        track(id="match-b", name="Tom and Jerry Theme D", search_rank=4, query_match=2),
        track(id="generic", name="Popular Classical Music", popularity=900_000_000, search_rank=5, query_match=0),
    ]

    selected = select_seeded_tracks(tracks, limit=4, seed=456)

    assert len(selected) == 4
    assert all(item.query_match >= 2 for item in selected)


def test_explicit_selection_blends_style_variants_and_suppresses_theme_copies():
    tracks = [
        track(
            id="intro-geek",
            name='Tom And Jerry Main Theme (From "Tom And Jerry")',
            artists=["Geek Music"],
            search_rank=1,
            query_match=3,
            search_variant=0,
            search_kind="exact",
        ),
        track(
            id="intro-kids",
            name='Tom And Jerry Main Theme (From "Tom And Jerry")',
            artists=["Just Kids"],
            search_rank=2,
            query_match=3,
            search_variant=0,
            search_kind="exact",
        ),
        track(
            id="score",
            name="Tom and Jerry Chase Around",
            artists=["Cartoon Score Orchestra"],
            search_rank=31,
            query_match=2,
            search_variant=1,
            search_kind="reference",
        ),
        track(
            id="cartoon-a",
            name="Classic Cartoon Chase",
            artists=["Animation Orchestra"],
            search_rank=121,
            query_match=0,
            search_variant=4,
            search_kind="style",
        ),
        track(
            id="cartoon-b",
            name="Old Cartoon Overture",
            artists=["Vintage Orchestra"],
            search_rank=151,
            query_match=0,
            search_variant=5,
            search_kind="style",
        ),
        track(
            id="cartoon-c",
            name="The Chase Cue",
            artists=["Animation Orchestra"],
            search_rank=152,
            query_match=0,
            search_variant=5,
            search_kind="style",
        ),
        track(
            id="cartoon-d",
            name="Golden Age Cartoon Score",
            artists=["Golden Age Orchestra"],
            search_rank=181,
            query_match=0,
            search_variant=6,
            search_kind="style",
        ),
    ]

    selected = select_seeded_tracks(tracks, limit=5, seed=123)

    assert len(selected) == 5
    assert sum(item.search_variant == 0 for item in selected) <= 1
    assert sum("Main Theme" in item.name for item in selected) == 0
    assert any(item.search_kind == "style" for item in selected)


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
