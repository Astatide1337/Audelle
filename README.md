# Audelle

Tell Audelle your vibe and get a playlist for the now. Playlists play through
YouTube's official IFrame player, can be downloaded as audio, and can be
shared as stateless links.

## How it works

- **Generate** — the browser sends your vibe to the local FastAPI API, which
  parses it, searches YouTube Music for candidates, and returns a playlist of
  validated YouTube video IDs.
- **Play** — audio streams through the official YouTube IFrame Player API
  (sanctioned embedding). The player supports play/pause, previous/next,
  restart, seek, and repeat off / one / all with automatic next-track
  playback. Queue and repeat state live in `Slideshow`; playback state lives in
  `web/src/lib/useYouTubeAudio.ts`.
- **Download** — `Download playlist` fetches each track's best available
  audio through `GET /api/audio/{videoId}` (resolved server-side with yt-dlp,
  streamed straight through — no re-encoding, no server-side storage) and packs
  them into a ZIP client-side. Progress, per-track failures, cancellation, and
  partial results are all surfaced in the UI.
- **Share** — `Share playlist` copies a link like
  `https://<host>/#v=<encoded-snapshot>`. The snapshot is the whole playlist
  (title, prompt, seed, tracks) deflated and base64url-encoded into the URL
  fragment. There is no database, no account, no token in the link; malformed,
  oversized, or outdated snapshots fail gracefully.

There is deliberately no Spotify/Apple/Deezer support, no OAuth, no playlist
export via the YouTube Data API, and no arbitrary-download endpoint: downloads
only ever accept video IDs that came from playlists Audelle generated.

## Development

### Server

```bash
cd server
uv sync                       # creates .venv and installs all deps (incl. yt-dlp)
uv run uvicorn app.main:app --reload
```

`pyproject.toml` + `uv.lock` are the source of truth — no `requirements.txt`.
`yt-dlp` is a regular dependency (via `uv sync`) for audio downloads. Without it,
playlist generation and playback still work; download requests return `503`.
YouTube may also challenge datacenter IPs with bot verification. Audelle reports
that condition as `503`; do not solve it by injecting a developer's browser
cookies into production. The selected deployment egress must pass a real
download smoke test and have an explicit credential/provider policy if YouTube
requires verification there.

### Web

```bash
cd web
npm install
npm run dev      # Vite dev server, proxies /api to 127.0.0.1:8000
npm run build    # typecheck + production bundle
npm run lint     # oxlint
```

### Tests

```bash
cd server && uv run pytest -q
```

The `live` tests call third-party catalog endpoints and are skipped by default.
Run them explicitly with `uv run pytest -m live -o addopts=`.

See `PRODUCTION_READINESS.md` before deploying anywhere public.
