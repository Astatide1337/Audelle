"""Stateless audio download support for generated playlists.

Audelle never accepts stream URLs from clients. A request carries only a bare
YouTube video ID; the best available audio stream is resolved here with yt-dlp,
transcoded to a high-quality MP3 stream, and proxied to the browser. Nothing is
written to disk and nothing is cached between requests.
"""

import asyncio
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi.responses import StreamingResponse

# Canonical YouTube video IDs are exactly eleven URL-safe characters.
VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"

RESOLVE_TIMEOUT_SECONDS = 30.0
STREAM_CONNECT_TIMEOUT_SECONDS = 15.0
STREAM_READ_TIMEOUT_SECONDS = 30.0
# Safety cap for one track; typical bestaudio files are well under 20 MB.
MAX_AUDIO_BYTES = 256 * 1024 * 1024
MP3_BITRATE = "320k"


class AudioDownloadError(Exception):
    """Raised when a track cannot be resolved or streamed."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ResolvedAudio:
    url: str
    content_type: str
    extension: str = "m4a"
    headers: tuple[tuple[str, str], ...] = ()


_AUDIO_TYPES = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "mp3": "audio/mpeg",
}

_STREAM_HEADER_ALLOWLIST = {
    "accept": "Accept",
    "accept-language": "Accept-Language",
    "sec-fetch-mode": "Sec-Fetch-Mode",
    "user-agent": "User-Agent",
}


def _safe_stream_headers(value: object) -> tuple[tuple[str, str], ...]:
    """Keep only non-secret request metadata required by YouTube media URLs."""
    if not isinstance(value, dict):
        return ()
    headers: list[tuple[str, str]] = []
    for raw_name, raw_value in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            continue
        name = _STREAM_HEADER_ALLOWLIST.get(raw_name.lower())
        if name and len(raw_value) <= 512 and "\r" not in raw_value and "\n" not in raw_value:
            headers.append((name, raw_value))
    return tuple(headers)


def _validate_stream_url(url: str) -> str:
    """Accept only HTTPS media URLs on YouTube's media delivery domain."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host.endswith(".googlevideo.com"):
        raise AudioDownloadError(502, "the audio resolver returned an invalid stream URL")
    return url


def _require_yt_dlp() -> str:
    """Locate yt-dlp: PATH first, then the bin dir of the running interpreter.

    The fallback covers uv-managed venvs started without activation, where
    .venv/bin is not on the inherited PATH.
    """
    executable = shutil.which("yt-dlp")
    if executable:
        return executable
    sibling = Path(sys.executable).parent / "yt-dlp"
    if sibling.is_file() and (shutil.which(str(sibling)) or sibling.stat().st_mode & 0o111):
        return str(sibling)
    raise AudioDownloadError(
        503,
        "audio downloads are unavailable on this server (yt-dlp is not installed)",
    )


def _require_ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    raise AudioDownloadError(
        503,
        "MP3 downloads are unavailable on this server (ffmpeg is not installed)",
    )


def resolve_audio(video_id: str) -> ResolvedAudio:
    """Resolve the best available audio format URL for one video ID.

    Runs synchronously; callers wrap it in asyncio.to_thread. yt-dlp emits one
    JSON object describing the selected best audio-only stream. This preserves
    the original bytes while letting us label WebM/Opus and M4A correctly.
    """
    executable = _require_yt_dlp()
    try:
        result = subprocess.run(
            [
                executable,
                "--no-warnings",
                "--no-cache-dir",
                "--no-playlist",
                "-f",
                "bestaudio/best",
                "--dump-single-json",
                "--skip-download",
                "--",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
            timeout=RESOLVE_TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioDownloadError(504, "resolving the audio took too long") from exc
    except subprocess.CalledProcessError as exc:
        stderr_tail = (exc.stderr or "").strip().splitlines()
        reason = stderr_tail[-1].lower() if stderr_tail else ""
        if "sign in" in reason or "not a bot" in reason or "cookies" in reason:
            raise AudioDownloadError(
                503,
                "YouTube is temporarily requiring verification from this server",
            ) from exc
        if "private" in reason or "unavailable" in reason or "removed" in reason:
            raise AudioDownloadError(404, "this track is no longer available on YouTube") from exc
        raise AudioDownloadError(502, "could not resolve an audio stream for this track") from exc

    try:
        metadata = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AudioDownloadError(502, "could not parse the resolved audio stream") from exc

    if not isinstance(metadata, dict):
        raise AudioDownloadError(502, "could not resolve an audio stream for this track")
    selected = metadata
    requested = metadata.get("requested_downloads")
    if isinstance(requested, list) and requested and isinstance(requested[0], dict):
        selected = requested[0]
    url = selected.get("url")
    extension = selected.get("ext")
    if not isinstance(url, str) or not isinstance(extension, str):
        raise AudioDownloadError(502, "could not resolve an audio stream for this track")
    extension = extension.lower()
    content_type = _AUDIO_TYPES.get(extension)
    if content_type is None:
        raise AudioDownloadError(502, "the selected audio format is not supported")

    return ResolvedAudio(
        url=_validate_stream_url(url),
        content_type=content_type,
        extension=extension,
        headers=_safe_stream_headers(selected.get("http_headers")),
    )


def _make_client() -> httpx.AsyncClient:
    """Factory so tests can substitute a transport without real network I/O."""
    limits = httpx.Limits(max_connections=1)
    timeout = httpx.Timeout(STREAM_READ_TIMEOUT_SECONDS, connect=STREAM_CONNECT_TIMEOUT_SECONDS)
    # Do not follow redirects: only the resolver-selected googlevideo URL has
    # passed the outbound destination policy above.
    return httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False)


async def _feed_ffmpeg_input(resolved: ResolvedAudio, stdin: asyncio.StreamWriter) -> None:
    """Validate and bound the upstream bytes before writing them to FFmpeg."""
    try:
        async with _make_client() as client:
            received = 0
            request_headers = dict(resolved.headers)
            # YouTube intentionally rate-limits an ordinary full-object
            # request. yt-dlp's own downloader requests a byte range; the
            # equivalent open-ended range avoids that throttle.
            request_headers["Range"] = "bytes=0-"
            async with client.stream("GET", resolved.url, headers=request_headers) as response:
                if response.status_code >= 400:
                    raise AudioDownloadError(502, "the audio stream could not be read")
                async for chunk in response.aiter_bytes(64 * 1024):
                    received += len(chunk)
                    if received > MAX_AUDIO_BYTES:
                        raise AudioDownloadError(502, "the audio stream exceeded the size limit")
                    stdin.write(chunk)
                    await stdin.drain()
    finally:
        if not stdin.is_closing():
            stdin.close()


async def _mp3_byte_stream(resolved: ResolvedAudio, ffmpeg: str):
    """Feed a validated upstream stream through one bounded FFmpeg process."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        "pipe:0",
        "-map",
        "0:a:0",
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        MP3_BITRATE,
        "-f",
        "mp3",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    producer = asyncio.create_task(_feed_ffmpeg_input(resolved, process.stdin))
    stderr_reader = asyncio.create_task(process.stderr.read(64 * 1024))
    sent = 0
    try:
        while chunk := await process.stdout.read(64 * 1024):
            sent += len(chunk)
            if sent > MAX_AUDIO_BYTES:
                raise AudioDownloadError(502, "the MP3 output exceeded the size limit")
            yield chunk
        await producer
        return_code = await process.wait()
        await stderr_reader
        if return_code != 0:
            raise AudioDownloadError(502, "the audio stream could not be converted to MP3")
    except httpx.HTTPError as exc:
        raise AudioDownloadError(502, "the audio stream was interrupted") from exc
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise AudioDownloadError(502, "the audio stream could not be converted to MP3") from exc
    finally:
        if not process.stdin.is_closing():
            process.stdin.close()
        if not producer.done():
            producer.cancel()
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
        await asyncio.gather(producer, stderr_reader, return_exceptions=True)


async def stream_audio(video_id: str) -> StreamingResponse:
    """Transcode the resolved audio to MP3 without buffering it or using disk."""
    resolved = await _resolve_async(video_id)
    ffmpeg = _require_ffmpeg()

    filename = f"audelle-{video_id}.mp3"
    return StreamingResponse(
        _mp3_byte_stream(resolved, ffmpeg),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


async def _resolve_async(video_id: str) -> ResolvedAudio:
    return await asyncio.to_thread(resolve_audio, video_id)


def audio_download_ready() -> bool:
    """Return whether the resolver and MP3 encoder executables are available."""
    try:
        _require_yt_dlp()
        _require_ffmpeg()
    except AudioDownloadError:
        return False
    return True
