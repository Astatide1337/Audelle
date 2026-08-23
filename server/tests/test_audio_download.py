import asyncio
import json
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from app.audio_service import audio_download as audio_mod
from app.audio_service.audio_download import AudioDownloadError, resolve_audio
from app import main as main_mod
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_audio_cache(monkeypatch, tmp_path):
    """Prevent developer/preview cache files from changing test outcomes."""
    monkeypatch.setattr(audio_mod, "AUDIO_CACHE_DIR", tmp_path / "audio-cache")
    audio_mod._CACHE_LOCKS.clear()
    yield
    audio_mod._CACHE_LOCKS.clear()


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


def test_returns_503_when_ffmpeg_is_missing(monkeypatch):
    _patch_resolve(monkeypatch)
    monkeypatch.setattr(audio_mod.shutil, "which", lambda _: None)
    res = client.get("/api/audio/dQw4w9WgXcQ")
    assert res.status_code == 503
    assert "ffmpeg" in res.json()["detail"]


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


def test_prepares_mp3_bytes_in_the_ephemeral_cache(monkeypatch):
    payload = b"ID3-fake-mp3-bytes" * 100

    async def fake_mp3_stream(resolved, ffmpeg):
        assert resolved.content_type == "audio/mp4"
        assert ffmpeg == "/usr/bin/ffmpeg"
        yield payload

    _patch_resolve(monkeypatch)
    monkeypatch.setattr(audio_mod, "_require_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(audio_mod, "_mp3_byte_stream", fake_mp3_stream)

    path = asyncio.run(audio_mod.prepare_audio_file("dQw4w9WgXcQ"))

    assert path.name == "audelle-dQw4w9WgXcQ.mp3"
    assert path.read_bytes() == payload


def test_maps_upstream_stream_failures_to_502(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(audio_mod, "_make_client", lambda: httpx.AsyncClient(transport=transport))

    class FakeStdin:
        def __init__(self):
            self.closed = False

        def is_closing(self):
            return self.closed

        def close(self):
            self.closed = True

        def write(self, _chunk):
            pass

        async def drain(self):
            pass

    stdin = FakeStdin()
    resolved = audio_mod.ResolvedAudio(url="https://streams.example/audio", content_type="audio/mp4")

    with pytest.raises(AudioDownloadError) as excinfo:
        asyncio.run(audio_mod._feed_ffmpeg_input(resolved, stdin))
    assert excinfo.value.status_code == 502
    assert stdin.closed


def test_feeds_ffmpeg_from_safari_compatible_upstream_range_response(monkeypatch):
    """The resolver stream must tolerate YouTube's normal 206 range response.

    YouTube throttles an unqualified full-object request.  Requesting an
    open-ended range is also the shape Safari expects from a media source, so
    keep this contract covered at the upstream boundary.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            206,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": "bytes 0-3/4",
                "Content-Length": "4",
            },
            content=b"data",
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(audio_mod, "_make_client", lambda: httpx.AsyncClient(transport=transport))

    class FakeStdin:
        def __init__(self):
            self.closed = False
            self.received = bytearray()

        def is_closing(self):
            return self.closed

        def close(self):
            self.closed = True

        def write(self, chunk):
            self.received.extend(chunk)

        async def drain(self):
            pass

    stdin = FakeStdin()
    resolved = audio_mod.ResolvedAudio(url="https://streams.example/audio", content_type="audio/mp4")

    asyncio.run(audio_mod._feed_ffmpeg_input(resolved, stdin))

    assert len(requests) == 1
    assert requests[0].headers["range"] == "bytes=0-"
    assert bytes(stdin.received) == b"data"
    assert stdin.closed


def test_concurrent_same_track_requests_share_resolution(monkeypatch):
    """Two taps for one track must not launch duplicate resolver work.

    This is intentionally a behavior test rather than an implementation test:
    each caller still receives an independent complete response body, while
    the expensive resolver/transcode work is shared in flight.
    """
    calls = 0
    encode_calls = 0
    resolver_started = asyncio.Event()
    release_resolver = asyncio.Event()
    resolved = audio_mod.ResolvedAudio(url="https://streams.example/audio", content_type="audio/mp4")

    async def fake_resolve(_video_id):
        nonlocal calls
        calls += 1
        resolver_started.set()
        await release_resolver.wait()
        return resolved

    async def fake_mp3_stream(_resolved, _ffmpeg):
        nonlocal encode_calls
        encode_calls += 1
        yield b"shared-audio"

    monkeypatch.setattr(audio_mod, "_resolve_async", fake_resolve)
    monkeypatch.setattr(audio_mod, "_require_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(audio_mod, "_mp3_byte_stream", fake_mp3_stream)

    async def exercise():
        first = asyncio.create_task(audio_mod.prepare_audio_file("AaBbCcDdEeF"))
        second = asyncio.create_task(audio_mod.prepare_audio_file("AaBbCcDdEeF"))
        await resolver_started.wait()
        # Let both callers reach the in-flight resolver before releasing it.
        await asyncio.sleep(0)
        release_resolver.set()
        paths = await asyncio.gather(first, second)
        return paths, [path.read_bytes() for path in paths]

    paths, bodies = asyncio.run(exercise())

    assert calls == 1
    assert encode_calls == 1
    assert len(paths) == 2
    assert paths[0] == paths[1]
    assert bodies == [b"shared-audio", b"shared-audio"]


def test_audio_endpoint_supports_safari_byte_ranges(monkeypatch):
    payload = b"0123456789"
    path = audio_mod.AUDIO_CACHE_DIR / "audelle-dQw4w9WgXcQ.mp3"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    async def use_cached_file(_video_id):
        return path

    monkeypatch.setattr(main_mod, "prepare_audio_file", use_cached_file)

    response = client.get(
        "/api/audio/dQw4w9WgXcQ",
        headers={"Range": "bytes=2-5"},
    )

    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert response.content == b"2345"
