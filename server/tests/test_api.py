from itertools import product

from fastapi.testclient import TestClient

from app.api.schemas import FiltersIn
from app.export_service.errors import ExportOAuthError
from app import main as main_module
from app.main import MAX_API_BODY_BYTES, _to_filters, app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert res.headers["cache-control"] == "no-store"
    assert len(res.headers["x-request-id"]) == 32


def test_request_id_is_correlated_only_when_it_matches_safe_format():
    supplied = client.get("/api/health", headers={"X-Request-ID": "request-42.ok"})
    rejected = client.get("/api/health", headers={"X-Request-ID": "bad value"})

    assert supplied.headers["x-request-id"] == "request-42.ok"
    assert rejected.headers["x-request-id"] != "bad value"
    assert len(rejected.headers["x-request-id"]) == 32


def test_rejects_empty_text():
    res = client.post("/api/playlist", json={"text": ""})
    assert res.status_code == 422


def test_rejects_missing_text():
    res = client.post("/api/playlist", json={})
    assert res.status_code == 422


def test_rejects_limit_out_of_range():
    res = client.post("/api/playlist", json={"text": "chill", "limit": 999})
    assert res.status_code == 422


def test_rejects_seed_out_of_range():
    res = client.post("/api/playlist", json={"text": "chill", "seed": 2**53})
    assert res.status_code == 422


def test_rejects_inverted_year_range():
    res = client.post(
        "/api/playlist",
        json={"text": "chill", "filters": {"year_from": 2025, "year_to": 2020}},
    )
    assert res.status_code == 422


def test_rejects_unknown_filter_fields_and_oversized_values():
    unknown = client.post("/api/playlist", json={"text": "chill", "filters": {"surprise": True}})
    oversized = client.post("/api/playlist", json={"text": "chill", "filters": {"language": "x" * 65}})
    assert unknown.status_code == 422
    assert oversized.status_code == 422


def test_rejects_unbounded_popularity_threshold():
    res = client.post("/api/playlist", json={"text": "chill", "filters": {"min_views": 10**15 + 1}})
    assert res.status_code == 422


def test_rejects_oversized_api_body_before_parsing():
    res = client.post("/api/playlist", content=b"{" + b"x" * (MAX_API_BODY_BYTES + 1) + b"}")
    assert res.status_code == 413


def test_export_provider_failures_are_generic_at_http_boundary(monkeypatch):
    def fail_start():
        raise ExportOAuthError("provider detail must not escape")

    monkeypatch.setattr(main_module, "start_export", fail_start)
    res = client.post("/api/export/youtube-music/start")

    assert res.status_code == 502
    assert res.json()["detail"] == "YouTube Music authorization failed; please try again"
    assert "provider detail" not in res.text


def test_all_64_supported_filter_combinations_cross_the_api_boundary():
    """Exercise every UI filter state without making 64 live catalog calls."""
    cases = product(
        (None, 2015),
        (None, 2024),
        ([], ["jazz"]),
        (None, "korean"),
        (None, 10_000, 1_000_000, 10_000_000),
    )

    count = 0
    for year_from, year_to, genres, language, min_views in cases:
        incoming = FiltersIn(
            year_from=year_from,
            year_to=year_to,
            genres=genres,
            language=language,
            min_views=min_views,
        )
        filters = _to_filters(incoming)
        assert filters.year_range == ((year_from, year_to) if year_from is not None or year_to is not None else None)
        assert filters.genres == genres
        assert filters.language == language
        assert filters.min_views == min_views
        count += 1

    assert count == 64


def test_generates_playlist_live():
    res = client.post("/api/playlist", json={"text": "hyped up for leg day at the gym", "limit": 5})
    assert res.status_code == 200
    body = res.json()
    assert body["plan"]["matched_anchors"][0]["id"] == "workout-hype"
    assert len(body["tracks"]) <= 5
    for track in body["tracks"]:
        assert track["id"]
        assert track["name"]
        assert track["watch_url"].startswith("https://music.youtube.com/watch?v=")


def test_applies_year_filter_live():
    res = client.post(
        "/api/playlist",
        json={"text": "beach vacation with friends", "filters": {"year_from": 2020, "year_to": 2024}, "limit": 5},
    )
    assert res.status_code == 200
    for track in res.json()["tracks"]:
        assert 2020 <= track["year"] <= 2024
