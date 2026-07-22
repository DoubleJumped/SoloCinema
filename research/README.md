# Research — Render bandwidth & collector hosting (2026-07-22)

Question: the Render Hobby workspace ran out of bandwidth running the
collector cron. Upgrade, or move somewhere free?

## What actually happened

Render Hobby includes only **5 GB of outbound bandwidth/month**, and Render
counts service-initiated calls to external databases as outbound — i.e.
**every Supabase write bills against the 5 GB**. The collector currently
makes ~2,830 Supabase requests per run (~6 per showing, for ~470 showings,
every 15 minutes) on fresh TLS connections, generating an estimated
**10–12 GB of egress/month — about double the quota**. Scraping traffic is
inbound and free; the build image is irrelevant; and Playwright/Chromium
never even runs in production (the build never installs the browser, so
Landmark silently uses the Atom HTTP fallback).

Details: [collector-efficiency-audit.md](collector-efficiency-audit.md) ·
[hosting-options.md](hosting-options.md)

## Recommendation

**Don't upgrade Render ($25/mo Pro is wildly oversized for this). Do both of
these instead:**

### 1. Fix the collector's write pattern (worth doing wherever it runs)

The top four fixes cut traffic roughly 10×, from ~10–12 GB to ~1 GB/month:

- Only write snapshots for showings actually probed this run — stop
  re-upserting all ~470 showings (including far-future ones) every 15 min.
- Use the `id` that `upsert_showing` already returns instead of the N+1
  lookup GETs; cache movie/theater ids in-process.
- Upsert each unique movie once per run, not once per showtime.
- Batch snapshot inserts (PostgREST accepts arrays) and reuse one pooled
  connection per host.

With just these, the collector fits back under Render's 5 GB and the
problem disappears for ~$1/month (Render's per-cron minimum).

### 2. Move the cron to GitHub Actions for a true $0

`DoubleJumped/SoloCinema` is already **public**, which means **unlimited
free Actions minutes** — the whole cron moves for $0 with a single workflow
file, and the Render cron service (and its $1/mo floor) can be deleted.
Since Playwright is unused dead weight, the job is plain Python + urllib and
runs on `ubuntu-latest` with zero fuss; secrets move to repo Actions
secrets.

Trade-off to accept: GitHub's `schedule` is best-effort — `*/15` runs
often land 5–30 minutes late at busy times and are occasionally skipped.
Snapshots are timestamped, so this degrades sample spacing, not
correctness. Schedule at `7,22,37,52 * * * *` to dodge the top-of-hour rush.

### Fallback

If Actions jitter ever proves unacceptable, an Oracle Always Free ARM VM
with system cron is the strongest genuinely-$0 alternative (real cron,
10 TB egress) at the cost of provisioning hassle and self-managed ops.
Supabase pg_cron + Edge Functions is $0 and elegant but requires rewriting
the collector in TypeScript/Deno — not worth it.

## Status (2026-07-22, same day)

Steps 1, 2, and most of 4 shipped:

- Efficiency fixes landed in `collector/` (commit "Cut collector Supabase
  traffic ~10x"): keep-alive connection + id caches in SupabaseRepository,
  snapshots only for probed showings, Cineplex capped at 7 days, prune
  hourly and non-fatal. First real run: Cineplex discovery dropped 851 →
  523, all sources success.
- `.github/workflows/collect.yml` is live with the three secrets set; the
  first `workflow_dispatch` run succeeded in ~7.5 min.
- Snapshot backlog cleared: `select public.prune_seat_snapshots('6 hours');`
  in the Supabase SQL editor deleted 29,637 rows (the editor session gets a
  longer statement timeout than the PostgREST RPC path, which is why the
  in-run prune had been 500ing).
- Migration complete: the first schedule-triggered Actions run succeeded
  (19:35 UTC — 13 min of scheduler jitter on the 19:22 slot, within normal
  range). `render.yaml` is removed; the Render cron service is suspended
  and can be deleted from the dashboard.

## Suggested order of work

1. Ship efficiency fixes 1–4 from the audit (one focused PR-sized change,
   mostly in `storage.py` and the three `write_*_showings` paths).
2. Add `.github/workflows/collect.yml` running
   `python -m collector.solocinema_collector.cli run-all --database-url supabase`
   on `7,22,37,52 * * * *` (16:00–05:59 UTC guard), with the three secrets.
3. Watch a day of runs, then suspend/delete the Render cron service and
   drop `render.yaml`.
4. Optional cleanup: remove the `playwright` extra from `pyproject.toml`
   and the dead probe paths, or keep them behind a flag for the day Atom
   breaks.
