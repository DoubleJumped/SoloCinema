# SoloCinema `/solocinema` V1 Plan

## Summary

Build a public Regina movie tracker as a self-contained `/solocinema` page in the existing Next.js/TypeScript `gwatson.ca` site on Vercel. V1 has no login, texting, or personal preferences; it automatically shows major-chain Regina screenings sorted by lowest inferred seat occupancy, with clear freshness and confidence labels.

## Agent Handoff

The codebase is ready for deployment wiring. Do not start new product feature
work until the live Vercel page and Render collector have been connected and
verified.

Next steps:

1. Deploy the Next.js app to Vercel with only browser-safe Supabase env vars:
   `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
2. Confirm deployed `/solocinema` reads live rows from Supabase instead of
   seeded sample data.
3. Create or connect the Render Cron job from `render.yaml`.
4. Add Render-only collector secrets: `SUPABASE_URL` and
   `SUPABASE_SERVICE_ROLE_KEY`.
5. Run the Render collector once, then confirm fresh rows appear in Supabase and
   on the deployed page.
6. Monitor the first few scheduled collector runs for stale data,
   chain-specific failures, or rotated Cineplex API credentials.

Keep secrets and machine-local artifacts out of git. Do not commit `.env`,
`.env.local`, `SUPABASE_SERVICE_ROLE_KEY`, `.venv`, `node_modules`, `.next`, or
local `tmp` files.

## Current Repo State

Last verified on June 9, 2026.

- The repo is on `main` with the V1 app, collector, Supabase schema, and Render
  cron config in place.
- `/solocinema` renders Regina screenings from Supabase when
  `SUPABASE_URL` and `SUPABASE_ANON_KEY` are present, and falls back to seeded
  sample data when they are absent.
- The Supabase project `SoloCinema` exists and has the expected tables and
  `solocinema_screenings` public read view.
- The live Supabase schema has been updated so `solocinema_screenings` uses
  `security_invoker = true`, and the repo schema now matches that setting.
- The collector can write fixture data to Supabase with the service role key.
- A capped live collector run succeeded against both supported chains:
  - Landmark: discovered 2, checked 2, failed 0.
  - Cineplex: discovered 2, checked 2, failed 0.
- Local app verification against live Supabase data succeeded. The page rendered
  current Cineplex and Landmark rows from `solocinema_screenings`.
- Local validation currently passes:
  - `npm test`
  - `npm run typecheck`
  - `python -m unittest discover -s collector/tests`

## Remaining Work

- Deploy the Next.js app to Vercel with only browser-safe Supabase env vars:
  `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
- Confirm the deployed `/solocinema` page reads from Supabase instead of sample
  data.
- Create or connect the Render Cron job from `render.yaml`.
- Add Render-only collector secrets: `SUPABASE_URL` and
  `SUPABASE_SERVICE_ROLE_KEY`.
- Run the Render job once manually or wait for the first scheduled run, then
  verify that fresh rows appear in Supabase and on the deployed page.
- Decide whether to remove the fixture smoke-test showing from production data
  after deployment validation.
- Monitor the first few scheduled collector runs for chain-specific failures,
  stale data, or rotated Cineplex API credentials.

## Architecture

- Frontend: add `/solocinema` to the existing Next.js app.
- Database: Supabase Postgres Free plan for showings and seat snapshots.
- Collector: Python 3.12 + Playwright + SQLAlchemy/SQLModel + Pydantic.
- Scheduler: Render Cron running the Python collector.
- Hosting cost target: Vercel `$0`, Supabase `$0`, Render Cron likely low single digits/month.
- V2-ready: keep the schema compatible with later Twilio SMS and custom movie/time alerts.

## Seat Data Strategy

- Use Atom Tickets as the current Landmark Regina V1 path. Atom is Landmark's
  public ticketing partner for Regina and exposes checkout seat-map fragments
  that can be counted without a login.
- Keep Landmark's own page as a discovery/probing fallback, but treat direct
  Playwright scraping there as currently blocked by Akamai Access Denied in this
  environment.
- Collect Cineplex Regina locations through Cineplex's own ticketing preview
  APIs. Southland uses location id `4108` and Normanview uses `4114`; showtime
  discovery comes from the theatrical showtimes API, and read-only seat layout
  plus preview availability come from the ticketing API.
- Counting method priority:
  - For Landmark, discover Atom checkout links and fetch `/checkout/{showtime_id}/seat-map` fragments.
  - Merge Atom price-area fragments by physical seat id so one seat is counted once.
  - For Cineplex, fetch `/v1/theatre/{location_id}/showtime/{vista_session_id}/seat-layout`
    and `/v1/theatre/{location_id}/showtime/{vista_session_id}/seat-availability?preview=true`.
  - Capture Playwright network responses and parse structured seat-map JSON when available.
  - Fall back to DOM parsing of rendered seat buttons/SVG/classes.
  - Avoid screenshot/image recognition unless absolutely necessary.
- Store the result as inferred occupied seats, not official tickets sold.
- Track scrape status per showing: `available`, `unknown`, or `failed`.
- Treat blocked, held, accessibility, unavailable, and sold seats carefully; if states are ambiguous, mark confidence lower instead of pretending precision.

## Product Behavior

- `/solocinema` opens directly to Regina results, no ZIP search.
- Main list shows:
  - movie,
  - theater,
  - showtime,
  - inferred occupied seats,
  - seat-map status,
  - last checked time,
  - ticket link.
- Default sort:
  - under-5 inferred occupied seats first,
  - then soonest showtime,
  - then theater/movie.
- Include a Show all screenings mode so the page is still useful when nothing is currently under threshold.
- Show freshness visibly, for example `Last checked 12 min ago`.
- Use honest labels like `0 inferred`, `4 inferred`, `unknown`, and `seat map unavailable`.

## Data Model

- `theaters`: chain, name, city, external id, ticketing URL.
- `movies`: normalized title, source title, poster URL when available, rating/runtime if available.
- `showings`: theater id, movie id, starts_at, format, auditorium if known, ticket URL, source id.
- `seat_snapshots`: showing id, checked_at, inferred_occupied, available_seats, total_sellable_seats, raw_status, confidence, error message.
- `scrape_runs`: chain, started_at, finished_at, status, count checked, count failed.
- Add uniqueness constraints around source ids and `(theater, movie, starts_at, format)` to avoid duplicates.

## Collector Schedule

- Discover/update showtimes daily and after weekly schedule refreshes.
- Check seat maps every 30-60 minutes during normal movie hours.
- Increase cadence for showings starting soon, especially within 2-6 hours.
- Stop checking after showtime starts or shortly after, depending on ticket flow availability.
- If a chain breaks, keep showing stale/unknown status rather than hiding everything silently.

## Test Plan

- [x] Build a data-quality spike before polishing UI:
  - [x] Confirm Landmark/Atom seat maps can be counted.
  - [x] Confirm Cineplex seat maps can be reached and counted.
  - [x] Save fixtures for network payloads or DOM snapshots.
- [x] Unit test seat-state parsing for available, occupied, blocked, accessible,
  and unknown states.
- [x] Unit test Atom theater-page parsing and multi-fragment seat-map merging.
- [x] Unit test Cineplex discovery, layout-plus-availability parsing, and local
  write orchestration.
- [x] Unit test sorting/filtering for under-5, unknown, stale, and
  all-screenings views.
- [x] Smoke test Supabase fixture writes for showings, snapshots, and scrape
  runs.
- [x] Run local Next.js page against Supabase-backed data before deploying.
- [x] Add collector dry-run mode that prints parsed results without writing to
  Supabase.
- [ ] Run the same end-to-end smoke test after Vercel and Render are connected.

## Assumptions

- V1 is public and shareable.
- No manual updating.
- No SMS/customization until v2.
- "Empty" means best-effort inferred from online seat maps, not guaranteed official sales data.
- Render Cron is preferred over Hetzner for now because it needs less ongoing server care.

## Sources

- [Walzr Empty Screenings](https://walzr.com/empty-screenings)
- [Landmark Regina showtimes](https://as.landmarkcinemas.com/showtimes/regina)
- [Atom Tickets Landmark Regina](https://www.atomtickets.com/theaters/landmark-cinemas-regina/49885)
- [Landmark Atom Tickets info](https://cms.landmarkcinemas.com/experiences/atom-tickets/)
- [Cineplex Southland](https://www.cineplex.com/theatre/cineplex-cinemas-southland)
- [Cineplex Southland showtimes API](https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes?language=en&locationId=4108)
- [Cineplex Normanview](https://www.cineplex.com/theatre/cineplex-cinemas-normanview)
- [Render pricing](https://render.com/pricing)
- [Supabase pricing](https://supabase.com/docs/pricing)
