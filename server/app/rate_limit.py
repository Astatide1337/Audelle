"""Small bounded per-client limiter for Audelle's anonymous expensive APIs."""

import ipaddress
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from fastapi import Request


@dataclass
class _Window:
    requests: deque[float] = field(default_factory=deque)


class ApiRateLimiter:
    """Fixed-window-cost limiter with bounded client memory."""

    def __init__(self, *, max_clients: int = 4096, window_seconds: int = 60):
        self.max_clients = max_clients
        self.window_seconds = window_seconds
        self._clients: OrderedDict[tuple[str, str], _Window] = OrderedDict()

    @staticmethod
    def _operation(request: Request) -> tuple[str, int] | None:
        path = request.url.path
        if request.method == "POST" and path == "/api/playlist":
            return "playlist", 12
        if request.method == "POST" and path.startswith("/api/audio/") and path.endswith("/prepare"):
            return "prepare", 20
        if request.method == "GET" and path.startswith("/api/audio/"):
            return "audio", 300
        return None

    @staticmethod
    def _client_key(request: Request) -> str:
        # Cloudflare overwrites this header at the public edge. The Kubernetes
        # NetworkPolicy permits only Audelle's dedicated tunnel to reach the pod.
        candidate = request.headers.get("cf-connecting-ip")
        if candidate:
            try:
                return str(ipaddress.ip_address(candidate.strip()))
            except ValueError:
                pass
        return request.client.host if request.client else "unknown"

    def retry_after(self, request: Request, *, now: float | None = None) -> int | None:
        operation = self._operation(request)
        if operation is None:
            return None
        name, limit = operation
        timestamp = time.monotonic() if now is None else now
        key = (self._client_key(request), name)
        window = self._clients.setdefault(key, _Window())
        self._clients.move_to_end(key)
        cutoff = timestamp - self.window_seconds
        while window.requests and window.requests[0] <= cutoff:
            window.requests.popleft()
        if len(window.requests) >= limit:
            return max(1, int(self.window_seconds - (timestamp - window.requests[0])))
        window.requests.append(timestamp)
        while len(self._clients) > self.max_clients:
            self._clients.popitem(last=False)
        return None

    def clear(self) -> None:
        self._clients.clear()
