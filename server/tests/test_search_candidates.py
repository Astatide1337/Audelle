import re

import pytest

import app.catalog_service.search_candidates as search_module
from app.catalog_service.errors import CatalogUnavailableError
from app.catalog_service.search_candidates import (
    _parse_views,
    build_search_term_candidates,
    merge_search_results,
    search_candidates,
)
from app.mood_parser.parse_vibe import QueryPlan
from app.shared.types import Filters


def plan(**overrides) -> QueryPlan:
    defaults = dict(genre_seeds=[], keyword_seeds=[], matched_anchors=[])
    defaults.update(overrides)
    return QueryPlan(**defaults)


def test_build_search_term_candidates_leads_with_fullest_variant():
    variants = build_search_term_candidates(plan(genre_seeds=["synthwave"], keyword_seeds=["night drive", "city"]), Filters())
    assert variants[0] == "night drive city synthwave"
    assert "synthwave" in variants
    assert variants[-1] == "night drive"


def test_build_search_term_candidates_prefers_user_genre_filter():
    variants = build_search_term_candidates(
        plan(genre_seeds=["synthwave"], keyword_seeds=["night drive"]), Filters(genres=["jazz"])
    )
    assert "jazz" in variants[0]
    assert "synthwave" not in variants[0]


def test_build_search_term_candidates_returns_nothing_for_empty_plan():
    assert build_search_term_candidates(plan(), Filters()) == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("73M", 73_000_000),
        ("2.5K", 2_500),
        ("1.3B", 1_300_000_000),
        ("542", 542),
        (None, 0),
        ("", 0),
        ("garbage", 0),
    ],
)
def test_parse_views(raw, expected):
    assert _parse_views(raw) == expected


def test_merge_search_results_interleaves_and_deduplicates_variants():
    first = [{"videoId": "a"}, {"videoId": "shared"}, {"videoId": "c"}]
    second = [{"videoId": "shared"}, {"videoId": "b"}, {"videoId": "d"}]

    merged = merge_search_results([first, second], pool_limit=5)

    assert [item["videoId"] for item in merged] == ["a", "shared", "b", "c", "d"]


def test_merge_search_results_respects_pool_limit():
    result_sets = [[{"videoId": f"track-{index}"} for index in range(10)]]
    assert len(merge_search_results(result_sets, pool_limit=4)) == 4


def _song_result(video_id: str, title: str) -> dict:
    video_id = re.sub(r"[^A-Za-z0-9_-]", "-", video_id)[:32]
    if len(video_id) < 6:
        video_id = f"track-{video_id}"[:32]
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": "Test Artist"}],
        "duration_seconds": 180,
        "views": "100K",
        "album": {"id": f"album-{video_id}"},
        "thumbnails": [{"url": "https://images.example.test/cover=w120-h120"}],
    }


@pytest.mark.asyncio
async def test_search_candidates_queries_every_variant_and_merges_results(monkeypatch):
    search_module._candidate_cache.clear()
    calls: list[str] = []

    async def fake_search(term: str) -> list[dict]:
        calls.append(term)
        return [_song_result(f"{term}-id", f"{term} song")]

    async def fake_lookup(album_id: str, sem) -> int:
        return 2024

    monkeypatch.setattr(search_module, "_search_once", fake_search)
    monkeypatch.setattr(search_module, "_lookup_year", fake_lookup)
    query_plan = plan(genre_seeds=["synthwave"], keyword_seeds=["night drive", "city"])
    variants = build_search_term_candidates(query_plan, Filters())

    results = await search_module.search_candidates(query_plan, Filters())

    assert set(calls) == set(variants)
    assert {item.id for item in results} == {
        re.sub(r"[^A-Za-z0-9_-]", "-", f"{variant}-id")[:32] for variant in variants
    }
    assert all(item.year == 2024 for item in results)


@pytest.mark.asyncio
async def test_search_candidates_keeps_partial_results_when_one_variant_is_unavailable(monkeypatch):
    search_module._candidate_cache.clear()
    query_plan = plan(genre_seeds=["ambient"], keyword_seeds=["focus", "study"])
    variants = build_search_term_candidates(query_plan, Filters())

    async def fake_search(term: str) -> list[dict]:
        if term == variants[0]:
            raise CatalogUnavailableError("temporary failure")
        return [_song_result(f"{term}-id", f"{term} song")]

    async def fake_lookup(album_id: str, sem) -> int:
        return 2024

    monkeypatch.setattr(search_module, "_search_once", fake_search)
    monkeypatch.setattr(search_module, "_lookup_year", fake_lookup)

    results = await search_module.search_candidates(query_plan, Filters())

    assert results
    assert all(item.id != f"{variants[0]}-id" for item in results)


@pytest.mark.asyncio
async def test_search_candidates_raises_when_every_variant_is_unavailable(monkeypatch):
    search_module._candidate_cache.clear()

    async def fake_search(term: str) -> list[dict]:
        raise CatalogUnavailableError(f"failed: {term}")

    monkeypatch.setattr(search_module, "_search_once", fake_search)

    with pytest.raises(CatalogUnavailableError):
        await search_module.search_candidates(plan(genre_seeds=["jazz"], keyword_seeds=["focus"]), Filters())


@pytest.mark.asyncio
async def test_search_candidates_rejects_malformed_provider_response(monkeypatch):
    search_module._candidate_cache.clear()

    async def fake_search(term: str):
        return None

    monkeypatch.setattr(search_module, "_search_once", fake_search)

    with pytest.raises(CatalogUnavailableError):
        await search_module.search_candidates(plan(genre_seeds=["jazz"], keyword_seeds=["focus"]), Filters())


@pytest.mark.asyncio
async def test_search_candidates_live_returns_well_formed_results():
    results = await search_candidates(plan(genre_seeds=["hip hop"], keyword_seeds=["workout", "gym"]), Filters())
    assert len(results) > 0
    for track in results:
        assert track.id
        assert track.name
        assert len(track.artists) > 0
        # Compilation/mix filtering should exclude anything wildly outside a normal song length.
        assert track.popularity >= 0
