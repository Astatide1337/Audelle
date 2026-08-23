# Audelle production handoff

This repository currently contains a local FastAPI service and a Vite/React
client. No deployment target, reverse proxy, container image, CI pipeline, or
infrastructure state is declared here. Treat the checklist below as a release
gate, not as evidence that a production deployment already exists.

The exact production host, API origin, static-host/CDN, TLS terminator, DNS
owner, deployment revision, and rollback artifact are still unknown. No live
system was changed during this readiness pass.

## Product surface relevant to operations

- `POST /api/playlist` — vibe → playlist of YouTube video IDs.
- `GET /api/audio/{video_id}` — streams one track's best available audio,
  resolved with yt-dlp. Stateless: no storage, no queue, nothing cached.
  The endpoint only accepts bare video IDs matching `^[A-Za-z0-9_-]{11}$`.
- Share links are URL-fragment snapshots decoded entirely in the browser; the
  server never sees them and stores nothing for them.

There is no OAuth, no Google/YouTube credential, no database, no accounts, and
no background queue anywhere in the product.

## Required runtime configuration

Set these values in the API environment, outside the repository:

```text
AUDELLE_ENV=production
AUDELLE_ALLOWED_ORIGINS=https://<your-web-origin>
AUDELLE_TRUSTED_HOSTS=<your-api-host>
AUDELLE_FORCE_HTTPS=true
```

Production refuses to start when the browser origins or trusted hosts are
missing or contain `*`, and it refuses to start unless
`AUDELLE_FORCE_HTTPS=true`.

Two runtime artifacts/concerns:

- The generated vocabulary embedding index at
  `server/app/mood_parser/vocab_embeddings.json` is a required runtime artifact
  and is intentionally included in release source.
 - `yt-dlp` is declared in `server/pyproject.toml` and pinned in `uv.lock`;
  `uv sync` installs it. Without it, `/api/audio/*` fails closed with `503`.
  Keep it pinned and update deliberately — YouTube extraction breaks regularly upstream.

The current workspace egress is challenged by YouTube with “Sign in to confirm
you’re not a bot,” so a real audio request returns `503`. This is a deployment
blocker for playlist ZIP export until the selected preview/production egress
passes the same smoke test. Do not place personal browser cookies in a server
secret as an ad-hoc workaround; that requires an explicit credential, rotation,
terms, and availability design.

Run Uvicorn behind a TLS-terminating proxy that sets forwarded headers, with a
narrow `--forwarded-allow-ips` value for that proxy. Do not expose Uvicorn
directly to the public internet.

## Deployment gates

- Serve `web/dist` from a production static server/CDN with an explicit CSP,
  HTTPS redirect, HSTS, and a narrow host allowlist. The Vite dev server is not
  a production server.
- Route the browser's relative `/api/*` requests to the API on the same public
  origin (or add a deliberate production API base URL); do not leave the Vite
  development proxy as the production traffic path.
- The CSP must account for the actual browser dependencies: the YouTube IFrame
  API/player, YouTube/Google thumbnail hosts, and the Google Fonts import. Keep
  `frame-ancestors` restrictive and do not use a blanket `*` source.
- Add edge rate limits and request-size limits for `/api/playlist` and
  especially `/api/audio/{video_id}` (it proxies large upstream responses). The
  API has per-process concurrency bounds, but those are not a substitute for a
  shared edge limit.
- The service is stateless and scales horizontally; there is no session store.
- Configure structured logs, alerting, and retention without logging request
  bodies.
- Prove TLS certificate rotation and rollback to the previous application
  artifact before release.
- Add a Python dependency advisory scan (`pip-audit` / `uv audit` or equivalent) to CI;
  the current environment does not have that tool installed.

## Verification performed in this workspace

- `uv run pytest -q` (from `server/`): all deterministic local tests pass; third-party
  smoke tests are marked `live` and skipped by default. The local suite includes
  the audio download endpoint contract (input validation, error mapping,
  streaming headers) — the environment is managed via `uv sync` from `pyproject.toml` + `uv.lock`.
- `npm run lint && npm run build`: passes.
- Production-mode import fails closed without origins/hosts; it succeeds with
  explicit origins, trusted hosts, and HTTPS enforcement.
- The logo and embedding release artifacts are present and readable; the
  embedding index is no longer ignored by source control.

The live public deployment, proxy/TLS configuration, CI result, alert delivery,
backup/recovery evidence, Python advisory scan, and a real end-to-end audio
download against YouTube remain operator-owned gates.

## Required operator decisions before deployment

1. Name the exact production target and deployment owner (host/container
   platform, region, and public web/API origins).
2. Choose the supported delivery path (CI/CD, image registry, or a manually
   reviewed release artifact) and record the commit SHA/image digest.
3. Provide the reverse-proxy/TLS and DNS plan, including forwarded-header trust,
   certificate renewal, HSTS scope, and rollback procedure.
4. Decide how yt-dlp is provisioned and patched in the serving image, and set
   an edge rate limit for audio downloads.
5. Run a Python dependency advisory scan and verify alerting, logs, backups,
   and restoration evidence in the chosen environment.
