# Collector Efficiency Audit — 2026-07-22

Why the Render Hobby-tier bandwidth ran out, and how to make the collector an
order of magnitude lighter. Produced by a code audit of
`collector/solocinema_collector/` at commit on `main`, 2026-07-22.

## Headline findings

1. **Playwright never runs on Render.** The build command
   (`render.yaml:10`) is `pip install -e ".[collector]"` and never runs
   `playwright install chromium`. Every `chromium.launch()` fails with
   "Executable doesn't exist", which `run_landmark_collection`
   (`landmark.py:226-234`) catches and silently falls back to the Atom HTTP
   scraper. **Landmark has been 100% Atom-HTTP in production.** The browser is
   dead weight in the build, not the bandwidth culprit.
2. **The real cost is request count, not any single big download.** Each run
   makes roughly **3,300 HTTPS requests** — ~470 GETs to Cineplex/Atom/IMAX
   and **~2,830 requests to Supabase** — each on a brand-new TLS connection
   (no pooling anywhere). At 56 runs/day that's ~185k requests/day.
3. **Estimated transfer: ~35–42 MB/run → ~65–70 GB/month** (inbound
   ~28–35 MB + egress ~6–7 MB per run). That sits right at a 100 GB quota
   line, and scales linearly with showing count — Cineplex discovery is
   unbounded by date, so a busy release week can blow past it.

## Update 2026-07-22: observed production numbers

A real Render log (17:38 UTC run) shows the estimates below were
conservative: **cineplex discovered=851, imax=120, landmark=93 — 1,064
showings per run, all of them "checked"** (vs the ~470 modeled). That's
~6,400 Supabase requests/run and roughly **20–25 GB/month of egress against
the 5 GB Hobby cap** — the quota burns out in about a week. The unbounded
Cineplex discovery (fix #5) is the multiplier: 851 showings means it is
pulling and probing a week-plus of showtimes every 15 minutes.

The same log shows two non-cost issues: `prune` failing with a Supabase
HTTP 500 (likely statement timeout — the snapshots table grows by ~60k
rows/day under this write pattern), which makes the whole run exit 1 and
the cron report "failed" even though all three sources succeeded; and a
benign `RuntimeError: Event loop is closed` traceback from the Playwright
driver subprocess being garbage-collected after its launch failure —
cosmetic noise.

## Resource profile per run

| Source | Discovery requests | Seat-probe requests | Showings written |
|---|---|---|---|
| Cineplex | 2 (1/theatre) | ~240 (layout + availability per showing) | ~250 (unbounded days) |
| Landmark/Atom | 7 (1/date, 7 days) | ~200 (checkout page + seat fragments) | ~180 |
| IMAX | ~8 (listing + calendars + key) | ~15 (SVG per reserved probe) | ~40 |

Supabase writes dominate: every discovered showing, every run, costs
**6 requests** —

- `upsert_movie` → 1 POST (`storage.py:357`)
- `upsert_showing` → 2 lookup GETs + 1 POST (`storage.py:373-395`)
- `insert_snapshot` → 1 lookup GET + 1 POST (`storage.py:397-416`)

~470 showings × 6 ≈ 2,830 requests, each carrying the ~220-byte service-role
JWT **twice** (`apikey` + `Authorization`, `storage.py:485-486`) on a fresh
TLS handshake.

## Structural cause, one line

Writing every showing every run × N+1 lookups × one movie-upsert per
*showtime* × zero connection reuse × unbounded Cineplex discovery.

## Fixes, ranked by impact

1. **Stop re-writing unchanged showings.** Only insert snapshots for showings
   actually probed this run; skip the "deferred/unknown" snapshots for
   out-of-window showings (`cineplex.py:306-311`, `landmark.py:283-289`,
   `imax.py:315-316`). Removes the majority of Supabase traffic.
2. **Kill the N+1 lookups.** `upsert_showing` already returns the row
   (`return=representation`) — use the returned `id` instead of the follow-up
   lookup GETs; cache theater/movie ids in-process. ~1,400 fewer requests/run.
3. **Dedupe movie upserts.** `upsert_movie` is called once per *showtime*
   (`cineplex.py:289`, `landmark.py:266`, `imax.py:290`) — the same ~30
   movies get POSTed hundreds of times per run. Upsert each unique movie once.
4. **Reuse connections and batch writes.** One pooled connection per host for
   the whole run; use PostgREST bulk insert (POST an array) for snapshots.
   Collapses thousands of TLS handshakes into a handful — the single biggest
   egress cut.
5. **Bound Cineplex discovery with a `days_ahead` cap** like Landmark's
   (`cineplex.py:248-252` has none).
6. **Tier the cadence by time-to-showtime.** Occupancy 3 days out barely
   moves (noted in `cineplex.py:26-29`); probe far-out showings hourly and
   only tighten to 15-min near showtime. Easy 50–75% cut in dead hours.
7. **Trim Supabase headers/payloads.** `Prefer: return=minimal` where the row
   isn't needed; send the JWT once, not twice.
8. **Skip already-started showings.** IMAX guards this (`imax.py:346`);
   Cineplex/Landmark probe windows are date-only and will probe a showing
   that started earlier today.
9. **Run `prune_snapshots` hourly, not every run** (`cli.py:358-363`).
10. **Drop the `playwright` extra entirely** (`pyproject.toml:9-11`) until/
    unless Atom breaks. The collector then becomes stdlib-urllib-only and can
    run in a 128 MB container anywhere.

## Other waste / latent bugs spotted

- Fresh CookieJar + opener built per Atom request in the discovery path
  (`atom.py:94-95, 130`), discarding cookies between calls.
- No retry/backoff on Cineplex, IMAX, or Supabase — single-shot
  `urlopen(timeout=30)`; a transient blip drops the whole showing. Atom is
  the only source with backoff.
- Global Atom throttle (`_last_request_at`, `atom.py:105`) serializes all
  Atom traffic to 1.2 s spacing → Landmark takes ~6–7 min/run, pushing total
  runtime toward the 15-minute cron interval.
- Latent Playwright waste if Chromium ever gets installed: `networkidle` +
  5 s extra wait with no `page.route` asset blocking
  (`landmark.py:414-416`, `playwright_probe.py:42-43`), and a fresh
  browser launched per probe/per date instead of reused.
- `run-all` prints full indented JSON summaries every run (`cli.py:366`) —
  log bloat, not bandwidth, but worth trimming.

## Portability notes

- Cineplex + IMAX are pure `urllib` — trivially portable to GitHub Actions,
  a tiny VM, or serverless.
- Landmark currently needs no browser either (Atom fallback is the de facto
  path). Only reintroduce Playwright if Atom breaks.
- Runtime per run is ~6–7 minutes today, dominated by the Atom 1.2 s
  throttle — relevant to per-minute-billed hosts (see
  [hosting-options.md](hosting-options.md)).
