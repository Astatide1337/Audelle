"""Audio preparation support for generated playlists.

Audelle never accepts stream URLs from clients. A request carries only a bare
YouTube video ID; the best available audio stream is resolved here with yt-dlp,
transcoded to a high-quality MP3 file in bounded ephemeral storage. The finite
file can then satisfy Safari's HTTP byte-range requests correctly.
"""

import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

# Canonical YouTube video IDs are exactly eleven URL-safe characters.
VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"

RESOLVE_TIMEOUT_SECONDS = 30.0
STREAM_CONNECT_TIMEOUT_SECONDS = 15.0
STREAM_READ_TIMEOUT_SECONDS = 30.0
# Safety cap for one track; typical bestaudio files are well under 20 MB.
MAX_AUDIO_BYTES = 256 * 1024 * 1024
MAX_MP3_BYTES = 64 * 1024 * 1024
MP3_BITRATE = "320k"
AUDIO_CACHE_DIR = Path(os.getenv("AUDELLE_AUDIO_CACHE_DIR", "/tmp/audelle-audio"))
AUDIO_CACHE_TTL_SECONDS = 6 * 60 * 60
AUDIO_CACHE_MAX_BYTES = 96 * 1024 * 1024
AUDIO_PREPARATION_CONCURRENCY = 2


@dataclass
class _CacheLockEntry:
    lock: asyncio.Lock
    users: int = 0


_CACHE_LOCKS: dict[str, _CacheLockEntry] = {}
_CACHE_LOCKS_GUARD = asyncio.Lock()
_PREPARATION_SLOTS = asyncio.Semaphore(AUDIO_PREPARATION_CONCURRENCY)


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
            if sent > MAX_MP3_BYTES:
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


def _existing_cache_files() -> list[tuple[Path, os.stat_result]]:
    """Snapshot cache metadata while tolerating concurrent atomic eviction."""
    files: list[tuple[Path, os.stat_result]] = []
    for path in AUDIO_CACHE_DIR.glob("audelle-*.mp3"):
        try:
            metadata = path.stat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(metadata.st_mode):
            files.append((path, metadata))
    return files


def _trim_audio_cache(keep: Path | None = None) -> None:
    """Remove stale/old ephemeral MP3s while preserving the active result."""
    AUDIO_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = time.time()
    for path, metadata in _existing_cache_files():
        if path != keep and now - metadata.st_mtime > AUDIO_CACHE_TTL_SECONDS:
            path.unlink(missing_ok=True)
    files = sorted(_existing_cache_files(), key=lambda item: item[1].st_mtime)
    total = sum(metadata.st_size for _, metadata in files)
    for path, metadata in files:
        if total <= AUDIO_CACHE_MAX_BYTES:
            break
        if path == keep:
            continue
        path.unlink(missing_ok=True)
        total -= metadata.st_size


@asynccontextmanager
async def _cache_lock(video_id: str):
    """Deduplicate one ID in flight without retaining attacker-chosen IDs."""
    async with _CACHE_LOCKS_GUARD:
        entry = _CACHE_LOCKS.setdefault(video_id, _CacheLockEntry(lock=asyncio.Lock()))
        entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        async with _CACHE_LOCKS_GUARD:
            entry.users -= 1
            if entry.users == 0 and _CACHE_LOCKS.get(video_id) is entry:
                del _CACHE_LOCKS[video_id]


async def prepare_audio_file(video_id: str) -> Path:
    """Create one finite MP3 per track and deduplicate concurrent callers."""
    target = AUDIO_CACHE_DIR / f"audelle-{video_id}.mp3"
    if target.is_file() and target.stat().st_size > 0:
        target.touch()
        return target

    async with _cache_lock(video_id):
        if target.is_file() and target.stat().st_size > 0:
            target.touch()
            return target

        try:
            await asyncio.wait_for(_PREPARATION_SLOTS.acquire(), timeout=0.05)
        except TimeoutError as exc:
            raise AudioDownloadError(429, "too many audio tracks are being prepared; please retry shortly") from exc

        temporary = AUDIO_CACHE_DIR / f".{video_id}-{uuid.uuid4().hex}.tmp"
        try:
            await asyncio.to_thread(_trim_audio_cache)
            resolved = await _resolve_async(video_id)
            ffmpeg = _require_ffmpeg()
            try:
                with temporary.open("xb") as output:
                    async for chunk in _mp3_byte_stream(resolved, ffmpeg):
                        output.write(chunk)
                if temporary.stat().st_size == 0:
                    raise AudioDownloadError(502, "the converted MP3 was empty")
                os.replace(temporary, target)
                await asyncio.to_thread(_trim_audio_cache, target)
                return target
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            _PREPARATION_SLOTS.release()


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
