# Audelle production baseline

Audelle entered production on 2026-08-23 at
`https://audelle.astatide.com`. This document records the deployed topology and
the checks expected for future releases; it is not a substitute for observing
the live system during a rollout.

## Deployed topology

- Argo CD reconciles the production overlay from the separate GitOps repository.
- The application is a single non-root pod scheduled to the `sohim` homelab
  node, fronted by a `ClusterIP` Service.
- A dedicated Cloudflare Tunnel pod also runs on Sohim and is the only ingress
  allowed to the application by NetworkPolicy.
- Cloudflare provides proxied DNS and public TLS for
  `audelle.astatide.com`. Sohim has no public application origin address.
- The service is stateless. Share data stays in URL fragments; prepared MP3s
  use a size- and time-bounded ephemeral cache.

The retired `audelle-preview.astatide.com` DNS record, tunnel route, Argo
Application, workload, Service, and NetworkPolicies have been removed.

## Runtime and security controls

- Production startup requires an exact allowed origin and trusted host plus
  HTTPS enforcement; API documentation is disabled.
- Trusted-host, forwarded-protocol, security-header, request-body, rate-limit,
  concurrency, outbound-host, response-size, and audio-cache bounds are applied.
- Audio resolution accepts HTTPS Googlevideo media URLs only, disables
  redirects, transcodes to MP3, and serves Safari-compatible byte ranges.
- Containers run without root, privilege escalation, writable root filesystem,
  or a service-account token. CPU, memory, and ephemeral-storage resources are
  bounded.
- Egress is limited to DNS and public HTTPS. Ingress is limited to Audelle's
  dedicated tunnel identity.
- CI pins actions, runs deterministic backend/frontend tests, Chromium and
  WebKit E2E checks, dependency advisory scans, and publishes an immutable image
  with SBOM and provenance.

Anonymous media preparation remains an inherently expensive public operation.
Application limits are a safety boundary, while Cloudflare and workload
telemetry should still be watched for distributed abuse.

## Release checklist

1. Merge reviewed application changes to `main` only after CI is green.
2. Record the commit and published image digest; never deploy a mutable tag.
3. Update the GitOps production overlay through review and let Argo CD reconcile.
4. Confirm the Argo Application is `Synced/Healthy`, the pod is on Sohim, and
   restart count and resource pressure remain normal.
5. Verify public DNS/TLS, homepage and readiness responses, playlist generation,
   WebKit playback and next-track advancement, MP3 `206` byte ranges, and ZIP
   download/cancellation behavior.
6. Observe logs and tunnel/workload metrics after rollout. Roll back by restoring
   the prior reviewed image digest in GitOps if user-visible checks regress.

Do not expose Uvicorn, the Kubernetes Service, a node port, or Sohim's address
to the public internet. Do not use personal YouTube cookies as a production
workaround. yt-dlp extraction compatibility changes regularly and should be
updated deliberately with the live audio checks above.
