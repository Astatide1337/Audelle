import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

import requests
from ytmusicapi.auth.oauth.credentials import OAuthCredentials

from .errors import (
    ExportCapacityReached,
    ExportDenied,
    ExportExpired,
    ExportOAuthError,
    ExportPending,
    ExportProviderError,
    ExportSessionNotFound,
)

logger = logging.getLogger(__name__)

YOUTUBE_DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_DATA_API_TIMEOUT_SECONDS = 20
OAUTH_HTTP_TIMEOUT_SECONDS = 20
YOUTUBE_DATA_API_TRANSIENT_RETRIES = 3
# The provider's 409 operation-aborted response is a short consistency window
# after playlist creation. Do not retry ambiguous 5xx writes: without an
# idempotency key, replaying a POST could create a duplicate external playlist.
YOUTUBE_DATA_API_TRANSIENT_STATUSES = {409}

# Matches Google's device-code expiry window (get_code()'s expires_in is ~1800s).
DEVICE_SESSION_TTL_SECONDS = 30 * 60
# Short-lived: only needs to survive the gap between a successful poll and the
# immediately-following create call.
AUTHORIZED_SESSION_TTL_SECONDS = 10 * 60
# Bound in-memory capability tokens so unauthenticated starts cannot exhaust a
# single process while users are completing the external device flow.
MAX_DEVICE_SESSIONS = 100
MAX_AUTHORIZED_SESSIONS = 100
GOOGLE_DEVICE_HOSTS = frozenset({"google.com", "www.google.com", "accounts.google.com"})
MAX_OAUTH_FIELD_LENGTH = 4096


class _TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", OAUTH_HTTP_TIMEOUT_SECONDS)
        return super().request(method, url, **kwargs)


@lru_cache(maxsize=1)
def _credentials() -> OAuthCredentials:
    return OAuthCredentials(
        client_id=os.environ["YTMUSIC_OAUTH_CLIENT_ID"],
        client_secret=os.environ["YTMUSIC_OAUTH_CLIENT_SECRET"],
        session=_TimeoutSession(),
    )


@dataclass
class ExportStart:
    session_id: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


@dataclass
class _DeviceSession:
    device_code: str
    created_at: float


@dataclass
class _AuthorizedSession:
    token: dict
    created_at: float


# In-memory only, matches the project's no-DB/ephemeral design (single-pod deployment).
# Tokens never leave the server — the browser only ever sees opaque session ids.
_device_sessions: dict[str, _DeviceSession] = {}
_authorized_sessions: dict[str, _AuthorizedSession] = {}
_polling_sessions: set[str] = set()
_session_lock = threading.RLock()


def _purge_expired(sessions: dict, ttl_seconds: float) -> None:
    now = time.time()
    for sid in [sid for sid, s in sessions.items() if now - s.created_at > ttl_seconds]:
        del sessions[sid]


def start_export() -> ExportStart:
    """Requests a device code the user completes in their own browser, on their own account."""
    with _session_lock:
        _purge_expired(_device_sessions, DEVICE_SESSION_TTL_SECONDS)
        if len(_device_sessions) >= MAX_DEVICE_SESSIONS:
            raise ExportCapacityReached()
        try:
            code = _credentials().get_code()
        except Exception as exc:
            logger.warning("Google device-code request failed: %s", exc.__class__.__name__)
            raise ExportOAuthError("device_code_request_failed") from exc

        if not isinstance(code, dict):
            raise ExportOAuthError("invalid_device_code_response")
        device_code = code.get("device_code")
        user_code = code.get("user_code")
        verification_url = code.get("verification_url")
        if not all(
            isinstance(value, str) and value and len(value) <= MAX_OAUTH_FIELD_LENGTH
            for value in (device_code, user_code, verification_url)
        ):
            raise ExportOAuthError("invalid_device_code_response")
        parsed_url = urlparse(verification_url)
        if parsed_url.scheme != "https" or parsed_url.hostname not in GOOGLE_DEVICE_HOSTS:
            logger.warning("Google returned an unexpected device verification host")
            raise ExportOAuthError("invalid_verification_url")
        try:
            expires_in = int(code.get("expires_in", 0))
            interval = max(2, min(int(code.get("interval", 5)), 60))
        except (TypeError, ValueError) as exc:
            raise ExportOAuthError("invalid_device_code_response") from exc
        if not 60 <= expires_in <= 24 * 60 * 60:
            raise ExportOAuthError("invalid_device_code_response")

        session_id = str(uuid.uuid4())
        _device_sessions[session_id] = _DeviceSession(device_code=device_code, created_at=time.time())
    return ExportStart(
        session_id=session_id,
        user_code=user_code,
        verification_url=verification_url,
        expires_in=expires_in,
        interval=interval,
    )


def poll_export_token(session_id: str) -> str:
    """
    Polls Google for the token. Raises ExportPending while the user hasn't
    finished the browser step yet — callers should retry after `interval`
    seconds from the original start_export() response. On success, returns an
    opaque authorized_session_id; the actual token never leaves this module.
    """
    with _session_lock:
        session = _device_sessions.get(session_id)
        if not session:
            raise ExportSessionNotFound(session_id)
        if session_id in _polling_sessions:
            raise ExportPending()
        _polling_sessions.add(session_id)

    try:
        try:
            result = _credentials().token_from_code(session.device_code)
        except Exception as exc:
            logger.warning("Google token poll failed: %s", exc.__class__.__name__)
            raise ExportOAuthError("token_poll_failed") from exc
        if not isinstance(result, dict):
            raise ExportOAuthError("invalid_token_response")
        error = result.get("error")

        if error in ("authorization_pending", "slow_down"):
            raise ExportPending()

        with _session_lock:
            _device_sessions.pop(session_id, None)
            if error == "expired_token":
                raise ExportExpired()
            if error == "access_denied":
                raise ExportDenied()
            if error:
                raise ExportOAuthError(str(error))
            access_token = result.get("access_token")
            refresh_token = result.get("refresh_token")
            if (
                not isinstance(access_token, str)
                or not access_token
                or len(access_token) > MAX_OAUTH_FIELD_LENGTH
            ):
                raise ExportOAuthError("invalid_token_response")
            if refresh_token is not None and (
                not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > MAX_OAUTH_FIELD_LENGTH
            ):
                raise ExportOAuthError("invalid_token_response")
            token_type = result.get("token_type", "Bearer")
            if not isinstance(token_type, str) or token_type.lower() != "bearer":
                token_type = "Bearer"

            _purge_expired(_authorized_sessions, AUTHORIZED_SESSION_TTL_SECONDS)
            if len(_authorized_sessions) >= MAX_AUTHORIZED_SESSIONS:
                raise ExportCapacityReached()
            authorized_id = str(uuid.uuid4())
            _authorized_sessions[authorized_id] = _AuthorizedSession(
                token={
                    "access_token": access_token,
                    "token_type": token_type,
                    **({"refresh_token": refresh_token} if refresh_token is not None else {}),
                },
                created_at=time.time(),
            )
            return authorized_id
    finally:
        with _session_lock:
            _polling_sessions.discard(session_id)


def _provider_error(response: requests.Response, operation: str) -> ExportProviderError:
    """Convert a provider response into a safe internal error.

    Google error payloads are useful in server logs but should not be reflected
    to the browser, where they can contain account or project details.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    error_payload = payload.get("error") or {}
    if isinstance(error_payload, dict):
        message = error_payload.get("message") or response.reason or "request rejected"
    else:
        message = str(error_payload)
    message = str(message).strip()
    logger.warning("YouTube Data API %s failed with HTTP %s: %s", operation, response.status_code, message[:240])
    return ExportProviderError(operation)


def _google_data_api_request(
    session: _AuthorizedSession,
    http: requests.Session,
    method: str,
    resource: str,
    operation: str,
    *,
    params: dict[str, str],
    payload: dict | None = None,
) -> dict:
    """Issue one authenticated YouTube Data API request.

    Google can briefly return ``409 operationAborted`` while a newly-created
    playlist is becoming writable. Retry that bounded transient window, and
    refresh an expired access token once without ever exposing the token to the
    browser.
    """
    refreshed_token = False
    transient_retries = 0
    while True:
        token = session.token
        access_token = token.get("access_token")
        if not access_token:
            raise ExportProviderError(operation)
        token_type = token.get("token_type", "Bearer")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            token_type = "Bearer"
        headers = {
            "Authorization": f"{token_type} {access_token}",
            "Accept": "application/json",
        }
        try:
            response = http.request(
                method,
                f"{YOUTUBE_DATA_API_BASE}/{resource}",
                params=params,
                json=payload,
                headers=headers,
                timeout=YOUTUBE_DATA_API_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.warning("YouTube Data API %s request failed: %s", operation, exc.__class__.__name__)
            raise ExportProviderError(operation) from exc

        if response.status_code == 401 and not refreshed_token and token.get("refresh_token"):
            try:
                refreshed = _credentials().refresh_token(token["refresh_token"])
            except Exception as exc:
                logger.warning("YouTube Data API token refresh failed: %s", exc.__class__.__name__)
                raise ExportProviderError(operation) from exc
            if (
                not isinstance(refreshed, dict)
                or not isinstance(refreshed.get("access_token"), str)
                or not refreshed["access_token"]
                or len(refreshed["access_token"]) > MAX_OAUTH_FIELD_LENGTH
            ):
                raise ExportProviderError(operation)
            session.token = {**token, **refreshed, "refresh_token": token["refresh_token"]}
            refreshed_token = True
            continue
        if response.status_code in YOUTUBE_DATA_API_TRANSIENT_STATUSES and transient_retries < YOUTUBE_DATA_API_TRANSIENT_RETRIES:
            transient_retries += 1
            delay = 0.5 * (2 ** (transient_retries - 1))
            logger.info(
                "Retrying YouTube Data API %s after HTTP %s (attempt %s/%s)",
                operation,
                response.status_code,
                transient_retries,
                YOUTUBE_DATA_API_TRANSIENT_RETRIES,
            )
            time.sleep(delay)
            continue
        if not 200 <= response.status_code < 300:
            raise _provider_error(response, operation)
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            logger.warning("YouTube Data API %s returned invalid JSON", operation)
            raise ExportProviderError(operation) from exc


def _delete_playlist(session: _AuthorizedSession, http: requests.Session, playlist_id: str) -> None:
    try:
        _google_data_api_request(
            session,
            http,
            "DELETE",
            "playlists",
            "delete_playlist",
            params={"id": playlist_id},
        )
    except ExportProviderError:
        logger.warning("Could not clean up partially created YouTube playlist")


def create_playlist_for_user(authorized_session_id: str, name: str, description: str, video_ids: list[str]) -> str:
    """Create a private playlist on the authorized user's YouTube account.

    YouTube Music's OAuth playlist-write endpoint currently rejects OAuth
    requests. The supported YouTube Data API writes to the same account and
    playlists are visible in YouTube Music, so use it for the side effect.
    """
    with _session_lock:
        session = _authorized_sessions.pop(authorized_session_id, None)
    if not session:
        raise ExportSessionNotFound(authorized_session_id)

    http = requests.Session()
    playlist_id: str | None = None
    try:
        response = _google_data_api_request(
            session,
            http,
            "POST",
            "playlists",
            "create_playlist",
            params={"part": "snippet,status"},
            payload={
                "snippet": {"title": name, "description": description},
                "status": {"privacyStatus": "private"},
            },
        )
        playlist_id = response.get("id")
        if not isinstance(playlist_id, str) or not playlist_id:
            raise ExportProviderError("create_playlist")

        # Preserve order while avoiding duplicate quota-consuming inserts.
        unique_video_ids = list(dict.fromkeys(video_ids))
        for video_id in unique_video_ids:
            _google_data_api_request(
                session,
                http,
                "POST",
                "playlistItems",
                "add_playlist_item",
                params={"part": "snippet"},
                payload={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            )
        return f"https://music.youtube.com/playlist?list={playlist_id}"
    except ExportProviderError:
        if playlist_id:
            _delete_playlist(session, http, playlist_id)
        raise
    finally:
        http.close()
