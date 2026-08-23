# Audelle web client

The React 19 and TypeScript frontend lives in `src/`. Vite provides the local
development server and produces the static bundle embedded in Audelle's
production container.

```bash
npm ci
npm run dev
npm test
npm run lint
npm run build
npm run test:e2e
```

The client uses same-origin `/api` requests. In development, Vite proxies them
to the local FastAPI server. Browser E2E coverage includes Chromium, WebKit,
responsive layouts, playback controls, and download behavior; the separate
manually dispatched workflow performs real WebKit playback against production.

Playback is owned by `src/lib/useAudioPlayback.ts`, playlist and control state
by `src/components/Slideshow/Slideshow.tsx`, and client-side MP3 ZIP creation by
`src/lib/download.ts`.
