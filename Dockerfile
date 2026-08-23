# syntax=docker/dockerfile:1.7
FROM node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS web-build
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.8.13@sha256:4de5495181a281bc744845b9579acf7b221d6791f99bcc211b9ec13f417c2853 AS uv

# yt-dlp uses a JavaScript runtime to solve YouTube's current player
# challenges. Without it, URLs may resolve but downloads are throttled enough
# to time out in the browser.
FROM denoland/deno:bin-2.5.1@sha256:49ba8ba927b71c772b4f244206dc1045d35f41d502e13c6f7a053e09821a58ab AS deno

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS python-build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/opt/fastembed-cache
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev
COPY server/app ./app
RUN uv run python -c "from app.mood_parser.embedder import warm_up; warm_up()"

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS runtime
ENV PATH=/app/server/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    FASTEMBED_CACHE_PATH=/opt/fastembed-cache \
    AUDELLE_WEB_DIST=/app/web
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libmp3lame \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 audelle \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp audelle
WORKDIR /app/server
COPY --from=deno /deno /usr/local/bin/deno
COPY --from=python-build --chown=10001:10001 /app/server/.venv ./.venv
COPY --from=python-build --chown=10001:10001 /app/server/app ./app
COPY --from=python-build --chown=10001:10001 /opt/fastembed-cache /opt/fastembed-cache
COPY --from=web-build --chown=10001:10001 /src/web/dist /app/web
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--no-server-header"]
