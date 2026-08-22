import time
from unittest.mock import MagicMock

import pytest

from app.export_service import youtube_music_export as export_mod
from app.export_service.errors import (
    ExportCapacityReached,
    ExportDenied,
    ExportExpired,
    ExportPending,
    ExportProviderError,
    ExportOAuthError,
    ExportSessionNotFound,
)


@pytest.fixture(autouse=True)
def clear_sessions():
    export_mod._device_sessions.clear()
    export_mod._authorized_sessions.clear()
    export_mod._polling_sessions.clear()
    yield
    export_mod._device_sessions.clear()
    export_mod._authorized_sessions.clear()
    export_mod._polling_sessions.clear()


def _mock_credentials(get_code=None, token_from_code=None):
    mock = MagicMock()
    if get_code is not None:
        mock.get_code.return_value = get_code
    if token_from_code is not None:
        mock.token_from_code.return_value = token_from_code
    return mock


def test_start_export_creates_session(monkeypatch):
    mock_creds = _mock_credentials(
        get_code={
            "device_code": "dc123",
            "user_code": "ABCD-1234",
            "verification_url": "https://google.com/device",
            "expires_in": 1800,
            "interval": 5,
        }
    )
    monkeypatch.setattr(export_mod, "_credentials", lambda: mock_creds)

    result = export_mod.start_export()

    assert result.user_code == "ABCD-1234"
    assert result.session_id in export_mod._device_sessions


def test_start_export_rejects_when_ephemeral_session_store_is_full(monkeypatch):
    monkeypatch.setattr(export_mod, "MAX_DEVICE_SESSIONS", 1)
    export_mod._device_sessions["existing"] = export_mod._DeviceSession(device_code="dc", created_at=time.time())

    with pytest.raises(ExportCapacityReached):
        export_mod.start_export()


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"device_code": "dc", "user_code": "ABCD", "verification_url": "http://google.com/device", "expires_in": 1800},
        {"device_code": "dc", "user_code": "ABCD", "verification_url": "https://evil.example/device", "expires_in": 1800},
        {"device_code": "dc", "user_code": "ABCD", "verification_url": "https://google.com/device", "expires_in": 10},
    ],
)
def test_start_export_rejects_untrusted_provider_code(monkeypatch, response):
    monkeypatch.setattr(export_mod, "_credentials", lambda: _mock_credentials(get_code=response))

    with pytest.raises(ExportOAuthError):
        export_mod.start_export()


def test_poll_does_not_allow_concurrent_provider_replay():
    export_mod._device_sessions["sid"] = export_mod._DeviceSession(device_code="dc", created_at=time.time())
    export_mod._polling_sessions.add("sid")

    with pytest.raises(ExportPending):
        export_mod.poll_export_token("sid")


def test_poll_pending_keeps_session_for_retry(monkeypatch):
    export_mod._device_sessions["sid"] = export_mod._DeviceSession(device_code="dc", created_at=time.time())
    monkeypatch.setattr(export_mod, "_credentials", lambda: _mock_credentials(token_from_code={"error": "authorization_pending"}))

    with pytest.raises(ExportPending):
        export_mod.poll_export_token("sid")
    assert "sid" in export_mod._device_sessions


def test_poll_expired_clears_session(monkeypatch):
    export_mod._device_sessions["sid"] = export_mod._DeviceSession(device_code="dc", created_at=time.time())
    monkeypatch.setattr(export_mod, "_credentials", lambda: _mock_credentials(token_from_code={"error": "expired_token"}))

    with pytest.raises(ExportExpired):
        export_mod.poll_export_token("sid")
    assert "sid" not in export_mod._device_sessions


def test_poll_denied(monkeypatch):
    export_mod._device_sessions["sid"] = export_mod._DeviceSession(device_code="dc", created_at=time.time())
    monkeypatch.setattr(export_mod, "_credentials", lambda: _mock_credentials(token_from_code={"error": "access_denied"}))

    with pytest.raises(ExportDenied):
        export_mod.poll_export_token("sid")


def test_poll_unknown_session_raises():
    with pytest.raises(ExportSessionNotFound):
        export_mod.poll_export_token("nonexistent")


def test_poll_success_hides_token_behind_opaque_session(monkeypatch):
    export_mod._device_sessions["sid"] = export_mod._DeviceSession(device_code="dc", created_at=time.time())
    token = {"access_token": "secret-token", "refresh_token": "secret-refresh", "expires_in": 3600}
    monkeypatch.setattr(export_mod, "_credentials", lambda: _mock_credentials(token_from_code=token))

    authorized_id = export_mod.poll_export_token("sid")

    assert "sid" not in export_mod._device_sessions
    assert authorized_id in export_mod._authorized_sessions
    assert export_mod._authorized_sessions[authorized_id].token == {
        "access_token": "secret-token",
        "token_type": "Bearer",
        "refresh_token": "secret-refresh",
    }


def test_create_playlist_unknown_session_raises():
    with pytest.raises(ExportSessionNotFound):
        export_mod.create_playlist_for_user("nonexistent", "name", "desc", ["v1"])


def test_create_playlist_success_and_single_use(monkeypatch):
    export_mod._authorized_sessions["aid"] = export_mod._AuthorizedSession(
        token={"access_token": "x", "token_type": "Bearer"}, created_at=time.time()
    )

    class Response:
        def __init__(self, body, status_code=200):
            self._body = body
            self.status_code = status_code
            self.reason = "OK"
            self.content = b"{}" if body else b""

        def json(self):
            return self._body

    class Session:
        def __init__(self):
            self.calls = []
            self.responses = [Response({"id": "PLxyz"}), Response({"id": "item-1"}), Response({"id": "item-2"})]

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return self.responses.pop(0)

        def close(self):
            pass

    fake_http = Session()
    monkeypatch.setattr(export_mod.requests, "Session", lambda: fake_http)

    url = export_mod.create_playlist_for_user("aid", "My Playlist", "desc", ["v1", "v2"])

    assert url == "https://music.youtube.com/playlist?list=PLxyz"
    assert [call[0] for call in fake_http.calls] == ["POST", "POST", "POST"]
    assert fake_http.calls[0][1].endswith("/playlists")
    assert fake_http.calls[0][2]["params"] == {"part": "snippet,status"}
    assert fake_http.calls[0][2]["json"] == {
        "snippet": {"title": "My Playlist", "description": "desc"},
        "status": {"privacyStatus": "private"},
    }
    assert fake_http.calls[1][2]["json"]["snippet"]["resourceId"] == {
        "kind": "youtube#video",
        "videoId": "v1",
    }
    assert fake_http.calls[0][2]["headers"]["Authorization"] == "Bearer x"
    assert "aid" not in export_mod._authorized_sessions


def test_create_playlist_deduplicates_video_ids(monkeypatch):
    export_mod._authorized_sessions["aid"] = export_mod._AuthorizedSession(
        token={"access_token": "x"}, created_at=time.time()
    )

    class Response:
        status_code = 200
        reason = "OK"
        content = b'{"id":"ok"}'

        def json(self):
            return {"id": "PLxyz"}

    class Session:
        def __init__(self):
            self.calls = 0

        def request(self, method, url, **kwargs):
            self.calls += 1
            return Response()

        def close(self):
            pass

    fake_http = Session()
    monkeypatch.setattr(export_mod.requests, "Session", lambda: fake_http)

    export_mod.create_playlist_for_user("aid", "Name", "Description", ["v1", "v1", "v2"])

    assert fake_http.calls == 3


def test_create_playlist_cleans_up_partial_playlist_and_consumes_session(monkeypatch):
    export_mod._authorized_sessions["aid"] = export_mod._AuthorizedSession(
        token={"access_token": "x"}, created_at=time.time()
    )

    class Response:
        def __init__(self, body, status_code=200):
            self._body = body
            self.status_code = status_code
            self.reason = "Bad Request" if status_code >= 400 else "OK"
            self.content = b"{}"

        def json(self):
            return self._body

    class Session:
        def __init__(self):
            self.calls = []
            self.responses = [
                Response({"id": "PLxyz"}),
                Response({"error": {"message": "invalid video"}}, status_code=400),
                Response({}, status_code=204),
            ]

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return self.responses.pop(0)

        def close(self):
            pass

    fake_http = Session()
    monkeypatch.setattr(export_mod.requests, "Session", lambda: fake_http)

    with pytest.raises(ExportProviderError):
        export_mod.create_playlist_for_user("aid", "Name", "Description", ["v1"])

    assert [call[0] for call in fake_http.calls] == ["POST", "POST", "DELETE"]
    assert fake_http.calls[-1][1].endswith("/playlists")
    assert fake_http.calls[-1][2]["params"] == {"id": "PLxyz"}
    assert "aid" not in export_mod._authorized_sessions


def test_create_playlist_refreshes_once_after_expired_access_token(monkeypatch):
    export_mod._authorized_sessions["aid"] = export_mod._AuthorizedSession(
        token={"access_token": "expired", "refresh_token": "refresh", "token_type": "Bearer"},
        created_at=time.time(),
    )

    class Response:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body
            self.reason = "Unauthorized" if status_code == 401 else "OK"
            self.content = b"{}" if status_code == 204 else b"{" + b'"id":"PLxyz"' + b"}"

        def json(self):
            return self._body

    class Session:
        def __init__(self):
            self.calls = []
            self.responses = [Response(401, {"error": {"message": "expired"}}), Response(200, {"id": "PLxyz"})]

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return self.responses.pop(0)

        def close(self):
            pass

    fake_http = Session()
    credentials = MagicMock()
    credentials.refresh_token.return_value = {"access_token": "fresh", "expires_in": 3600}
    monkeypatch.setattr(export_mod.requests, "Session", lambda: fake_http)
    monkeypatch.setattr(export_mod, "_credentials", lambda: credentials)

    export_mod.create_playlist_for_user("aid", "Name", "Description", [])

    assert fake_http.calls[0][2]["headers"]["Authorization"] == "Bearer expired"
    assert fake_http.calls[1][2]["headers"]["Authorization"] == "Bearer fresh"
    credentials.refresh_token.assert_called_once_with("refresh")


def test_create_playlist_retries_transient_provider_abort(monkeypatch):
    export_mod._authorized_sessions["aid"] = export_mod._AuthorizedSession(
        token={"access_token": "x"}, created_at=time.time()
    )

    class Response:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body
            self.reason = "Conflict" if status_code == 409 else "OK"
            self.content = b"{}"

        def json(self):
            return self._body

    class Session:
        def __init__(self):
            self.calls = 0
            self.responses = [
                Response(409, {"error": {"message": "The operation was aborted."}}),
                Response(200, {"id": "PLxyz"}),
            ]

        def request(self, method, url, **kwargs):
            self.calls += 1
            return self.responses.pop(0)

        def close(self):
            pass

    fake_http = Session()
    monkeypatch.setattr(export_mod.requests, "Session", lambda: fake_http)
    monkeypatch.setattr(export_mod.time, "sleep", lambda _: None)

    url = export_mod.create_playlist_for_user("aid", "Name", "Description", [])

    assert url == "https://music.youtube.com/playlist?list=PLxyz"
    assert fake_http.calls == 2


def test_start_export_live_against_real_google_endpoint():
    """Safe, non-mutating: requesting a device code doesn't touch any account."""
    result = export_mod.start_export()
    assert result.verification_url.startswith("https://")
    assert len(result.user_code) > 0
    assert result.expires_in > 0
