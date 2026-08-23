"""ASGI receive boundary that limits API bodies even without Content-Length."""

from starlette.responses import JSONResponse


class ApiBodyLimitMiddleware:
    def __init__(self, app, *, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope.get("path", "").startswith("/api/")
            or scope.get("method") not in {"POST", "PUT", "PATCH"}
        ):
            await self.app(scope, receive, send)
            return

        received = 0
        exceeded = False
        pending_messages = []

        async def limited_receive():
            nonlocal exceeded, received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def buffered_send(message):
            pending_messages.append(message)

        await self.app(scope, limited_receive, buffered_send)
        if exceeded:
            response = JSONResponse(
                status_code=413,
                content={"detail": "request body is too large"},
                headers={
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                },
            )
            await response(scope, receive, send)
            return
        for message in pending_messages:
            await send(message)
