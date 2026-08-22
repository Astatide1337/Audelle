# Audelle production handoff

This repository currently contains a local FastAPI service and a Vite/React
client. No deployment target, reverse proxy, container image, CI pipeline, or
infrastructure state is declared here. Treat the checklist below as a release
gate, not as evidence that a production deployment already exists.

The exact production host, API origin, static-host/CDN, TLS terminator, DNS
owner, deployment revision, and rollback artifact are still unknown. No live
system was changed during this readiness pass.

The current Git baseline is also not a release revision: `HEAD` tracks only
`LICENSE`, while the application, assets, and readiness notes are untracked in
the working tree. Review and commit the intended source before any deployment;
do not treat a local working tree or an unpushed change as production
provenance.

## Required runtime configuration

Set these values in the API environment, outside the repository:

```text
AUDELLE_ENV=production
AUDELLE_ALLOWED_ORIGINS=https://<your-web-origin>
AUDELLE_TRUSTED_HOSTS=<your-api-host>
AUDELLE_FORCE_HTTPS=true
YTMUSIC_OAUTH_CLIENT_ID=<secret-managed-value>
YTMUSIC_OAUTH_CLIENT_SECRET=<secret-managed-value>
```

Production refuses to start when the browser origins or trusted hosts are
missing, contain `*`, or when OAuth credentials are absent. It also refuses to
start unless `AUDELLE_FORCE_HTTPS=true`. Keep OAuth credentials in a secret
manager or an 0600-mounted environment file; never put them in a frontend
bundle or logs.

The generated vocabulary embedding index at
`server/app/mood_parser/vocab_embeddings.json` is a required runtime artifact
and is intentionally included in release source. The model download/cache is a
separate image-build or startup concern and must not depend on an interactive
developer machine.

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
- Add edge rate limits and request-size limits for `/api/playlist` and all
  export routes. The API has per-process concurrency bounds, but those are not
  a substitute for a shared edge limit.
- The OAuth capability/session store is process-local memory. Run one API
  instance, or move device/authorized sessions to an encrypted shared store
  before scaling horizontally.
- Configure structured logs, alerting, and retention without logging OAuth
  tokens, client secrets, authorization codes, or request bodies.
- Prove TLS certificate rotation, rollback to the previous application
  artifact, and recovery of any external playlist side effects before release.
- Move the Google OAuth consent screen out of Testing (or explicitly limit the
  product to approved test users) and complete Google's verification requirements
  for the YouTube scope. The earlier `403 access_denied` is expected for an
  account that is not on the OAuth test-user list.
- Add a Python dependency advisory scan (`pip-audit` or an equivalent) to CI;
  the current environment does not have that tool installed.

## Verification performed in this workspace

- `server/.venv/bin/pytest -q -k 'not live'`: 59 local tests pass; the five
  tests whose names include `live` were not run in this safety pass because
  they call third-party catalog/Google endpoints.
- `npm run lint && npm run build`: passes.
- `npm audit --audit-level=high` and production-only audit: zero findings.
- Production-mode import fails closed without origins/hosts; it succeeds with
  explicit origins, trusted hosts, OAuth values, and HTTPS enforcement.
- A local production-mode Uvicorn smoke test through a simulated trusted proxy
  returned the expected HTTP-to-HTTPS redirect, HTTPS health response, security
  headers, HSTS, and CORS allowlist behavior.
- The logo and embedding release artifacts are present and readable; the
  embedding index is no longer ignored by source control.

The live public deployment, proxy/TLS configuration, CI result, alert delivery,
backup/recovery evidence, and Python advisory scan remain operator-owned gates.

## Required operator decisions before deployment

1. Name the exact production target and deployment owner (host/container
   platform, region, and public web/API origins).
2. Choose the supported delivery path (CI/CD, image registry, or a manually
   reviewed release artifact) and record the commit SHA/image digest.
3. Provide the reverse-proxy/TLS and DNS plan, including forwarded-header trust,
   certificate renewal, HSTS scope, and rollback procedure.
4. Decide whether the process-local OAuth session store is acceptable as a
   single-instance constraint. Do not scale the API horizontally until those
   sessions move to an encrypted shared store or the product explicitly
   accepts that limitation.
5. Run a Python dependency advisory scan and verify alerting, logs, backups,
   and restoration evidence in the chosen environment.
