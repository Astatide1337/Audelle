import asyncio
import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from .api.schemas import (
    ExportCreateRequest,
    ExportCreateResponse,
    ExportPollRequest,
    ExportPollResponse,
    ExportStartResponse,
    FiltersIn,
    MatchedAnchorOut,
    MAX_PLAYLIST_SEED,
    PlaylistRequest,
    PlaylistResponse,
    QueryPlanOut,
    TrackOut,
)
from .catalog_service.errors import CatalogUnavailableError
from .export_service import errors as export_errors
from .export_service.youtube_music_export import create_playlist_for_user, poll_export_token, start_export
from .mood_parser.parse_vibe import parse_vibe
from .playlist_service.generate_playlist import generate_playlist
from .shared.types import Filters

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


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
            "YTMUSIC_OAUTH_CLIENT_ID",
            "YTMUSIC_OAUTH_CLIENT_SECRET",
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


app = FastAPI(
    title="Audelle API",
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
EXPORT_START_CONCURRENCY = 4
EXPORT_POLL_CONCURRENCY = 8
export_start_slots = asyncio.Semaphore(EXPORT_START_CONCURRENCY)
export_poll_slots = asyncio.Semaphore(EXPORT_POLL_CONCURRENCY)

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
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
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


@app.post("/api/export/youtube-music/start", response_model=ExportStartResponse)
async def export_start() -> ExportStartResponse:
    try:
        await asyncio.wait_for(export_start_slots.acquire(), timeout=0.05)
    except TimeoutError as exc:
        raise HTTPException(status_code=429, detail="too many export authorizations are in progress") from exc
    try:
        start = await asyncio.to_thread(start_export)
    except export_errors.ExportCapacityReached as exc:
        raise HTTPException(status_code=429, detail="too many export authorizations are in progress") from exc
    except export_errors.ExportOAuthError as exc:
        raise HTTPException(status_code=502, detail="YouTube Music authorization failed; please try again") from exc
    finally:
        export_start_slots.release()
    return ExportStartResponse(
        session_id=start.session_id,
        user_code=start.user_code,
        verification_url=start.verification_url,
        expires_in=start.expires_in,
        interval=start.interval,
    )


@app.post("/api/export/youtube-music/poll", response_model=ExportPollResponse)
async def export_poll(req: ExportPollRequest) -> ExportPollResponse:
    try:
        await asyncio.wait_for(export_poll_slots.acquire(), timeout=0.05)
    except TimeoutError as exc:
        raise HTTPException(status_code=429, detail="too many export authorizations are in progress") from exc
    try:
        authorized_session_id = await asyncio.to_thread(poll_export_token, req.session_id)
        return ExportPollResponse(status="complete", authorized_session_id=authorized_session_id)
    except export_errors.ExportPending:
        return ExportPollResponse(status="pending")
    except export_errors.ExportSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="export session not found or already used") from exc
    except export_errors.ExportExpired as exc:
        raise HTTPException(status_code=410, detail="the code expired before it was used, start again") from exc
    except export_errors.ExportDenied as exc:
        raise HTTPException(status_code=403, detail="authorization was denied") from exc
    except export_errors.ExportOAuthError as exc:
        raise HTTPException(status_code=502, detail="YouTube Music authorization failed; please start again") from exc
    except export_errors.ExportCapacityReached as exc:
        raise HTTPException(status_code=429, detail="too many export authorizations are in progress") from exc
    finally:
        export_poll_slots.release()


@app.post("/api/export/youtube-music/create", response_model=ExportCreateResponse)
async def export_create(req: ExportCreateRequest) -> ExportCreateResponse:
    try:
        external_url = await asyncio.to_thread(
            create_playlist_for_user, req.authorized_session_id, req.name, req.description, req.track_ids
        )
        return ExportCreateResponse(external_url=external_url)
    except export_errors.ExportSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="authorization expired or already used, please export again") from exc
    except export_errors.ExportProviderError as exc:
        raise HTTPException(status_code=502, detail="YouTube playlist export failed; please try again") from exc
