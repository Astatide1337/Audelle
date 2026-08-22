import asyncio
import json
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

from app.audio_service import audio_download as audio_mod
from app.audio_service.audio_download import AudioDownloadError, resolve_audio
from app import main as main_mod
from app.main import app

client = TestClient(app)


def _patch_resolve(monkeypatch, url="https://streams.example/audio", content_type="audio/mp4"):
    monkeypatch.setattr(audio_mod, "_resolve_async", _async_return(audio_mod.ResolvedAudio(url=url, content_type=content_type)))


def _async_return(value):
    async def resolver(_video_id):
        return value

    return resolver


def test_rejects_video_ids_that_are_not_eleven_safe_characters():
    for bad in ("short", "way-too-long-to-be-real", "has%20space"):
        res = client.get(f"/api/audio/{bad}")
        assert res.status_code == 422


def test_path_traversal_attempts_never_reach_the_handler():
    assert client.get("/api/audio/..%2Fetc").status_code == 404


@pytest.fixture()
def fake_yt_dlp(monkeypatch):
    monkeypatch.setattr(audio_mod.shutil, "which", lambda _: "/usr/bin/yt-dlp")


def test_returns_503_when_yt_dlp_is_missing(monkeypatch):
    monkeypatch.setattr(audio_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(audio_mod.sys, "executable", "/tmp/nonexistent/python")
    res = client.get("/api/audio/dQw4w9WgXcQ")
    assert res.status_code == 503
    assert "yt-dlp" in res.json()["detail"]


def test_maps_unavailable_videos_to_404(fake_yt_dlp, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "yt-dlp", stderr="ERROR: Video unavailable\n")

    monkeypatch.setattr(audio_mod.subprocess, "run", fail)
    with pytest.raises(AudioDownloadError) as excinfo:
        resolve_audio("dQw4w9WgXcQ")
    assert excinfo.value.status_code == 404


def test_maps_youtube_bot_challenge_to_service_unavailable(fake_yt_dlp, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            "yt-dlp",
            stderr="ERROR: Sign in to confirm you’re not a bot. Use --cookies for authentication.\n",
        )

    monkeypatch.setattr(audio_mod.subprocess, "run", fail)
    with pytest.raises(AudioDownloadError) as excinfo:
        resolve_audio("dQw4w9WgXcQ")
    assert excinfo.value.status_code == 503
    assert "verification" in excinfo.value.detail


def test_maps_generic_resolver_failures_to_502(fake_yt_dlp, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "yt-dlp", stderr="something odd happened\n")

    monkeypatch.setattr(audio_mod.subprocess, "run", fail)
    with pytest.raises(AudioDownloadError) as excinfo:
        resolve_audio("dQw4w9WgXcQ")
    assert excinfo.value.status_code == 502


def test_maps_resolver_timeout_to_504(fake_yt_dlp, monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("yt-dlp", 30)

    monkeypatch.setattr(audio_mod.subprocess, "run", slow)
    with pytest.raises(AudioDownloadError) as excinfo:
        resolve_audio("dQw4w9WgXcQ")
    assert excinfo.value.status_code == 504


def test_resolver_preserves_webm_format_metadata(fake_yt_dlp, monkeypatch):
    metadata = {
        "requested_downloads": [{
            "url": "https://rr1---sn-test.googlevideo.com/videoplayback?id=123",
            "ext": "webm",
            "http_headers": {
                "User-Agent": "yt-dlp browser agent",
                "Accept": "*/*",
                "Cookie": "must-not-leave-the-resolver",
                "Authorization": "must-not-leave-the-resolver",
            },
        }]
    }
    monkeypatch.setattr(
        audio_mod.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(metadata), ""),
    )

    resolved = resolve_audio("dQw4w9WgXcQ")

    assert resolved.content_type == "audio/webm"
    assert resolved.extension == "webm"
    assert dict(resolved.headers) == {"User-Agent": "yt-dlp browser agent", "Accept": "*/*"}


def test_resolver_rejects_non_googlevideo_stream_urls(fake_yt_dlp, monkeypatch):
    metadata = {"url": "http://127.0.0.1/internal", "ext": "m4a"}
    monkeypatch.setattr(
        audio_mod.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(metadata), ""),
    )

    with pytest.raises(AudioDownloadError) as excinfo:
        resolve_audio("dQw4w9WgXcQ")
    assert excinfo.value.status_code == 502


def test_streams_audio_bytes_with_attachment_headers(monkeypatch):
    payload = b"fake-audio-bytes" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Range"] == "bytes=0-"
        return httpx.Response(200, content=payload, headers={"Content-Type": "audio/mp4"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(audio_mod, "_make_client", lambda: httpx.AsyncClient(transport=transport))
    _patch_resolve(monkeypatch)

    with client.stream("GET", "/api/audio/dQw4w9WgXcQ") as res:
        assert res.status_code == 200
        assert res.headers["content-type"] == "audio/mp4"
        assert 'attachment; filename="audelle-dQw4w9WgXcQ.m4a"' in res.headers["content-disposition"]
        body = b"".join(res.iter_bytes())

    assert body == payload


def test_audio_concurrency_slot_is_held_until_stream_background_cleanup(monkeypatch):
    slots = asyncio.Semaphore(1)

    async def fake_stream(_video_id):
        async def body():
            yield b"audio"

        return StreamingResponse(body(), media_type="audio/webm")

    monkeypatch.setattr(main_mod, "audio_slots", slots)
    monkeypatch.setattr(main_mod, "stream_audio", fake_stream)

    response = asyncio.run(main_mod.download_audio("dQw4w9WgXcQ"))
    assert slots.locked()
    assert response.background is not None

    asyncio.run(response.background())
    assert not slots.locked()


def test_maps_upstream_stream_failures_to_502(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(audio_mod, "_make_client", lambda: httpx.AsyncClient(transport=transport))
    _patch_resolve(monkeypatch)

    with pytest.raises(AudioDownloadError) as excinfo:
        client.get("/api/audio/dQw4w9WgXcQ")
    assert excinfo.value.status_code == 502
