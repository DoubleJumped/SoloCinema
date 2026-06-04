# SoloCinema `/solocinema` V1 Plan

## Summary

Build a public Regina movie tracker as a self-contained `/solocinema` page in the existing Next.js/TypeScript `gwatson.ca` site on Vercel. V1 has no login, texting, or personal preferences; it automatically shows major-chain Regina screenings sorted by lowest inferred seat occupancy, with clear freshness and confidence labels.

## Architecture

- Frontend: add `/solocinema` to the existing Next.js app.
- Database: Supabase Postgres Free plan for showings and seat snapshots.
- Collector: Python 3.12 + Playwright + SQLAlchemy/SQLModel + Pydantic.
- Scheduler: Render Cron running the Python collector.
- Hosting cost target: Vercel `$0`, Supabase `$0`, Render Cron likely low single digits/month.
- V2-ready: keep the schema compatible with later Twilio SMS and custom movie/time alerts.

## Seat Data Strategy

- Scrape Landmark Regina first, because its public page references seat-map previews.
- Add Cineplex Regina locations second, using the ticket flow if seat maps are reachable without login or checkout.
- Counting method priority:
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

- Build a data-quality spike before polishing UI:
  - Confirm Landmark seat maps can be counted.
  - Confirm Cineplex seat maps can be reached and counted.
  - Save fixtures for network payloads or DOM snapshots.
- Unit test seat-state parsing for available, occupied, blocked, accessible, and unknown states.
- Unit test sorting/filtering for under-5, unknown, stale, and all-screenings views.
- Integration test Supabase writes for showings, snapshots, and scrape runs.
- Run local Next.js page against seeded sample data before deploying.
- Add collector dry-run mode that prints parsed results without writing to Supabase.

## Assumptions

- V1 is public and shareable.
- No manual updating.
- No SMS/customization until v2.
- "Empty" means best-effort inferred from online seat maps, not guaranteed official sales data.
- Render Cron is preferred over Hetzner for now because it needs less ongoing server care.

## Sources

- [Walzr Empty Screenings](https://walzr.com/empty-screenings)
- [Landmark Regina showtimes](https://as.landmarkcinemas.com/showtimes/regina)
- [Cineplex Normanview](https://www.cineplex.com/theatre/cineplex-cinemas-normanview)
- [Render pricing](https://render.com/pricing)
- [Supabase pricing](https://supabase.com/docs/pricing)
