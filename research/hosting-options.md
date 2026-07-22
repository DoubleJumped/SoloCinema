# Free Cron Hosting Options — 2026-07-22

Where to run the collector for $0 (or near it). Workload baseline: ~56
runs/day (~1,700/month), each run currently ~6–7 minutes (dominated by the
Atom 1.2 s request throttle), plain-HTTPS only in practice (see
[collector-efficiency-audit.md](collector-efficiency-audit.md) — Playwright
never actually runs in production). Writes to external Supabase.

Claims verified against official pricing/docs pages where possible;
aggregator-sourced numbers flagged.

## Why Render ran out of bandwidth

- Render **Hobby workspace includes 5 GB outbound bandwidth/month**, then
  $0.15/GB (render.com/docs/new-workspace-plans).
- Bandwidth = **egress only**, and Render explicitly counts
  "service-initiated outbound traffic … such as calls to an external
  database" (render.com/docs/outbound-bandwidth). **Every Supabase write
  counts.**
- The audit estimates ~6–7 MB egress/run → **~10–12 GB/month — 2× the
  5 GB cap.** Mystery solved: it's the chatty Supabase write pattern, not
  the scraping (inbound is free) and not the build/image.
- Render cron jobs bill per-second of runtime with a **$1/month minimum per
  cron service**. Upgrade path: new Pro plan is **$25/month flat** —
  massively overkill for this.

## Comparison

| Option | Monthly cost | Schedule reliability | Setup | Key gotchas |
|---|---|---|---|---|
| **Render Hobby (status quo + efficiency fixes)** | ~$1 (cron floor) + $0 overage once egress < 5 GB | High — true cron | None | 5 GB egress cap; Supabase writes count |
| **GitHub Actions (repo is already public)** | **$0 — unlimited minutes on public repos** | Med — runs can be delayed 5–30 min at busy times, occasionally dropped | Low | 60-day no-commit auto-disable of schedules; per-job minute rounding (irrelevant when free) |
| GitHub Actions if repo were private | ~$18/mo (5,100 min vs 2,000 free) | Med | Low | Not applicable — repo is public |
| **Supabase pg_cron + Edge Functions** | $0 | High | Med–high | **Requires a Deno/TypeScript rewrite** (collector is Python); 150 s wall-clock limit per function; no Chromium |
| **Oracle Cloud Always Free (ARM A1 VM + system cron)** | $0, 10 TB egress | High — real cron, always on | Med | "Out of host capacity" provisioning lottery; self-managed patching/uptime; free caps possibly reduced to 2 OCPU/12 GB in 2026 (unverified) |
| Cloud Run Jobs + Cloud Scheduler | $0 for light HTTP jobs at reduced footprint; ~$5–11/mo at 2 vCPU/2 GiB × current runtimes | High | Med–high | Only 1 GiB/mo free egress; Docker + IAM setup |
| AWS Lambda + EventBridge Scheduler | ~$0 for light jobs (1M req + 400k GB-s free) | High | High | 15-min max timeout (fine); container packaging if Chromium ever needed |
| Fly.io | ~$2/mo — no free tier anymore | Low for this — `--schedule` only does hourly/daily/monthly, no `*/15` | Med | Skip |
| Railway | ~$5/mo floor after trial | High | Low | Skip (not free) |
| Cloudflare Workers / Browser Rendering | $0 but can't run the collector (no Python, browser tier is ~10 min/day) | High | — | Skip |
| Northflank free tier | Likely $0 (2 free jobs, 24/7, real cron) | High | Med | Free-tier RAM/CPU ceilings unpublished — verify before relying on it |
| Koyeb | — | — | — | Free tier discontinued (2026, post-Mistral acquisition). Skip |

## Notes on the two front-runners

### GitHub Actions (public repo → unlimited free)

- `DoubleJumped/SoloCinema` is already public, so scheduled workflows cost
  nothing at any frequency or runtime.
- Playwright is a non-issue today (unused), and even if reintroduced,
  `playwright install --with-deps chromium` works on `ubuntu-latest`.
- Secrets (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
  `CINEPLEX_SUBSCRIPTION_KEY`) go in repo Actions secrets — not exposed to
  fork PRs.
- **Schedule jitter is the one real trade-off**: `*/15` runs commonly land
  5–30 min late during GitHub's busy windows, and a queued run is
  occasionally skipped. For a seat-occupancy time series this means uneven
  sample spacing, not data corruption — snapshots are timestamped. Mitigate
  by scheduling off the top of the hour (e.g. `7,22,37,52`).
- **60-day rule**: scheduled workflows are disabled after 60 days without a
  commit. SoloCinema gets regular pushes, but a monthly keepalive
  (workflow-commits-a-timestamp) removes the risk.

### Oracle Always Free A1 VM

- The strongest option if schedule regularity ever becomes critical:
  real system cron, always-on, 10 TB free egress, runs all three sources.
- Costs: the provisioning lottery ("out of host capacity" in popular
  regions), plus owning OS patching and uptime yourself. Worth it only if
  GitHub Actions jitter proves unacceptable in practice.
