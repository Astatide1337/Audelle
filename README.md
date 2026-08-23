# Audelle

Audelle turns a written vibe into a playable, shareable playlist. The production
application is available at [audelle.astatide.com](https://audelle.astatide.com).

## Features

- Generate varied playlists from natural-language prompts and optional year,
  genre, language, and popularity filters.
- Play 320 kbps MP3 audio with preloading, seeking, previous/next controls, and
  repeat modes. Playback uses native browser audio and supports Safari/iPhone.
- Download the playlist as a client-generated ZIP of MP3 files. Cancelling a
  download discards it instead of saving a partial archive.
- Share a playlist through a compressed URL-fragment snapshot. Audelle has no
  accounts, cookies, database, or persistent playlist storage.

## Architecture

The React/Vite frontend and FastAPI API are built into one container and served
from the same origin. Playlist discovery uses YouTube Music catalog metadata.
Audio preparation uses yt-dlp and ffmpeg, stores only bounded ephemeral MP3
cache files, and supports HTTP byte ranges for browser playback.

Production runs as a non-root Kubernetes workload on the `sohim` homelab node.
It is reachable only through a dedicated Cloudflare Tunnel; the Kubernetes
Service remains `ClusterIP`, so Sohim's address is not exposed publicly. Argo CD
owns reconciliation from the separate GitOps repository. Images are pinned by
commit and digest and are published with SBOM and provenance attestations.

## Local development

Requirements: Python 3.11, [uv](https://docs.astral.sh/uv/), Node.js 24, npm,
ffmpeg with `libmp3lame`, and yt-dlp's supported JavaScript runtime.

Start the API:

```bash
cd server
uv sync --frozen
uv run uvicorn app.main:app --reload
```

Start the frontend in another terminal:

```bash
cd web
npm ci
npm run dev
```

Vite proxies relative `/api` requests to `127.0.0.1:8000` during development.

## Verification

```bash
cd server
uv sync --frozen
uv run pytest -q

cd ../web
npm ci --ignore-scripts
npm test
npm run lint
npm run build
npx playwright install chromium webkit
npm run test:e2e
```

Tests marked `live` contact third-party services and are excluded from the
deterministic default suite. Run them deliberately with:

```bash
cd server
uv run pytest -m live -o addopts=
```

The manually dispatched live-browser workflow targets production and verifies
real WebKit playback. CI also runs Python and npm advisory scans.

## Production operations

Required runtime configuration:

```text
AUDELLE_ENV=production
AUDELLE_ALLOWED_ORIGINS=https://audelle.astatide.com
AUDELLE_TRUSTED_HOSTS=audelle.astatide.com
AUDELLE_FORCE_HTTPS=true
```

Production fails closed if these values are absent or use wildcards. Public
traffic is Cloudflare → the dedicated Sohim tunnel → the internal Kubernetes
Service. Deployments and rollbacks are performed by changing the immutable
image reference in GitOps; do not apply repository manifests manually or put
personal browser cookies into production secrets.
