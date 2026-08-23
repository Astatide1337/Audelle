import asyncio
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

from .api.schemas import (
    FiltersIn,
    MatchedAnchorOut,
    MAX_PLAYLIST_SEED,
    PlaylistRequest,
    PlaylistResponse,
    QueryPlanOut,
    TrackOut,
)
from .audio_service.audio_download import AudioDownloadError, audio_download_ready, prepare_audio_file
from .catalog_service.errors import CatalogUnavailableError
from .mood_parser.embedder import warm_up
from .mood_parser.parse_vibe import parse_vibe
from .playlist_service.generate_playlist import generate_playlist
from .shared.types import Filters

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _csv_env(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.getenv("AUDELLE_ENV", "development").strip().lower()
if APP_ENV not in {"development", "test", "production"}:
    raise RuntimeError("AUDELLE_ENV must be development, test, or production")

ALLOWED_ORIGINS = _csv_env(
    "AUDELLE_ALLOWED_ORIGINS",
    ["http://localhost:5173", "http://127.0.0.1:5173"],
)
TRUSTED_HOSTS = _csv_env("AUDELLE_TRUSTED_HOSTS", ["localhost", "127.0.0.1", "[::1]", "testserver"])
FORCE_HTTPS = _bool_env("AUDELLE_FORCE_HTTPS")
MAX_API_BODY_BYTES = 64 * 1024

if APP_ENV == "production":
    missing_production_config = [
        name
        for name in (
            "AUDELLE_ALLOWED_ORIGINS",
            "AUDELLE_TRUSTED_HOSTS",
        )
        if not os.getenv(name, "").strip()
    ]
    if missing_production_config:
        raise RuntimeError(
            "missing required production configuration: " + ", ".join(missing_production_config)
        )
    if not FORCE_HTTPS:
        raise RuntimeError("AUDELLE_FORCE_HTTPS=true is required in production")
    if any("*" in value for value in (*ALLOWED_ORIGINS, *TRUSTED_HOSTS)):
        raise RuntimeError("wildcard origins and hosts are not allowed in production")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail startup before receiving traffic if the embedded model cannot be
    # loaded. Container builds pre-populate its cache; this check verifies the
    # actual runtime artifact rather than relying on the image build alone.
    if APP_ENV == "production":
        await asyncio.to_thread(warm_up)
    yield


app = FastAPI(
    title="Audelle API",
    lifespan=lifespan,
    docs_url=None if APP_ENV == "production" else "/docs",
    redoc_url=None if APP_ENV == "production" else "/redoc",
    openapi_url=None if APP_ENV == "production" else "/openapi.json",
)

if TRUSTED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)
if FORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)

# Search invokes embedding work and a third-party catalog. A bounded queue
# keeps one local worker responsive under bursts without changing normal use.
PLAYLIST_CONCURRENCY = 4
playlist_slots = asyncio.Semaphore(PLAYLIST_CONCURRENCY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After", "X-Request-ID"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "")
    if (
        not request_id
        or len(request_id) > 128
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in request_id)
    ):
        request_id = secrets.token_hex(16)
    content_length = request.headers.get("content-length")
    oversized_body = False
    if request.url.path.startswith("/api/") and content_length:
        try:
            oversized_body = int(content_length) > MAX_API_BODY_BYTES
        except ValueError:
            oversized_body = True
    try:
        if oversized_body:
            response = JSONResponse(
                status_code=413,
                content={"detail": "request body is too large", "requestId": request_id},
                headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
            )
        else:
            response = await call_next(request)
    except Exception:
        # Keep unexpected errors generic at the HTTP boundary while retaining
        # a correlation id and a server-side traceback for operators.
        logger.exception("Unhandled request failure request_id=%s path=%s", request_id, request.url.path)
        response = JSONResponse(
            status_code=500,
            content={"detail": "internal server error", "requestId": request_id},
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    else:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
            "script-src 'self' https://www.youtube.com https://s.ytimg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://*.googleusercontent.com https://i.ytimg.com; "
            "media-src 'self'; "
            "connect-src 'self'; frame-src https://www.youtube.com https://www.youtube-nocookie.com",
        )
    response.headers.setdefault("X-Request-ID", request_id)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if APP_ENV == "production" and request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def _to_filters(f: FiltersIn) -> Filters:
    year_range = (f.year_from, f.year_to) if f.year_from is not None or f.year_to is not None else None
    return Filters(year_range=year_range, genres=f.genres, language=f.language, min_views=f.min_views)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/api/health/ready")
async def health_ready():
    if not audio_download_ready():
        raise HTTPException(status_code=503, detail="audio resolver is unavailable")
    return {"status": "ready"}


@app.post("/api/playlist", response_model=PlaylistResponse)
async def create_playlist(req: PlaylistRequest) -> PlaylistResponse:
    try:
        await asyncio.wait_for(playlist_slots.acquire(), timeout=0.05)
    except TimeoutError as exc:
        raise HTTPException(status_code=429, detail="playlist generation is busy; please retry shortly") from exc

    try:
        plan = await asyncio.to_thread(parse_vibe, req.text)
        filters = _to_filters(req.filters)
        try:
            request_seed = req.seed if req.seed is not None else secrets.randbelow(MAX_PLAYLIST_SEED + 1)
            playlist = await generate_playlist(plan, filters, req.limit, request_seed)
        except CatalogUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "catalog_unavailable", "retryAfterMs": exc.retry_after_ms},
            ) from exc
    finally:
        playlist_slots.release()

    return PlaylistResponse(
        plan=QueryPlanOut(
            genre_seeds=plan.genre_seeds,
            keyword_seeds=plan.keyword_seeds,
            matched_anchors=[MatchedAnchorOut(id=m.id, similarity=m.similarity) for m in plan.matched_anchors],
        ),
        tracks=[TrackOut(**vars(t)) for t in playlist.tracks],
        seed=playlist.seed,
    )


@app.get("/api/audio/{video_id}")
async def download_audio(video_id: str):
    """Stream the best available audio track for one generated video ID.

    The caller may only pass a bare YouTube video ID; stream URLs are resolved
    server-side and never accepted as input. Bytes are proxied straight through
    with no server-side storage.
    """
    if VIDEO_ID_RE.fullmatch(video_id) is None:
        raise HTTPException(status_code=422, detail="invalid video id")

    try:
        audio_path = await prepare_audio_file(video_id)
    except AudioDownloadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=f"audelle-{video_id}.mp3",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=21600"},
    )


@app.post("/api/audio/{video_id}/prepare", status_code=204)
async def prepare_audio(video_id: str):
    """Prepare a finite MP3 before the browser needs to start playback."""
    if VIDEO_ID_RE.fullmatch(video_id) is None:
        raise HTTPException(status_code=422, detail="invalid video id")

    try:
        await prepare_audio_file(video_id)
    except AudioDownloadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return Response(status_code=204)


WEB_DIST = Path(os.getenv("AUDELLE_WEB_DIST", Path(__file__).parents[2] / "web" / "dist"))
if WEB_DIST.is_dir():
    # Mounted after API routes so same-origin production serves the Vite bundle
    # without weakening or shadowing the API boundary.
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
