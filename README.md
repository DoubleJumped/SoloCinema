# SoloCinema

Find the emptiest movie screenings in Regina.

SoloCinema tracks showtimes at Cineplex and Landmark theatres, infers how many
seats are taken from each showing's public seat map, and lists everything on a
split-flap departures board sorted so the quietest screenings come first.

**Live at [solocinema.vercel.app](https://solocinema.vercel.app)**

## How it works

- **Web app** — a Next.js page (`app/solocinema/`) hosted on Vercel. It reads
  screenings from Supabase, and falls back to bundled sample data when no
  database is configured.
- **Collector** — a Python CLI (`collector/`) that runs as a Render cron job
  every 15 minutes during movie hours. It discovers showtimes, counts seats
  from public seat maps, and writes snapshots to Supabase.
- **Database** — Supabase Postgres (`supabase/schema.sql`). The browser reads
  through a public view with the anon key; only the collector writes, using
  the service-role key.

Seat data comes from two sources:

- **Landmark** — showtimes and reserved-seat maps via Atom Tickets, Landmark's
  official ticketing partner. Atom serves separate seat-map fragments per price
  area; the parser merges them by physical seat id so a seat is never counted
  twice.
- **Cineplex** — the same public showtimes and seat-layout/availability APIs
  the Cineplex website uses, in read-only preview mode.
- **Kramer IMAX** — the Saskatchewan Science Centre's Vantix ATMS ticketing
  site publishes per-showtime remaining counts, and reserved-seating shows
  expose a per-seat SVG chart. See `docs/imax-research.md` for the full
  reverse-engineering notes.

Occupancy is *inferred* from public reserved-seating maps, not official sales
data, and the UI labels it that way (`4 inferred`, `unknown`) alongside a
last-checked time.

## Development

Frontend:

```bash
npm install
npm run dev        # http://localhost:3000/solocinema
npm test
npm run typecheck
```

Without Supabase credentials the page renders seeded sample data, so the app
and its tests run fully offline.

Collector:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[collector]"
python -m unittest discover -s collector/tests
```

Useful commands — discovery and probes never write anywhere:

```bash
# discover current showtimes
python -m collector.solocinema_collector.cli discover-landmark-atom
python -m collector.solocinema_collector.cli discover-cineplex
python -m collector.solocinema_collector.cli discover-imax

# probe a single seat map
python -m collector.solocinema_collector.cli probe-cineplex-seatmap \
  --location-id 4108 --vista-session-id <session-id>
python -m collector.solocinema_collector.cli probe-imax-seatmap --sch <schedule-id>

# full collection run into local SQLite
python -m collector.solocinema_collector.cli run-all \
  --database-url sqlite:///tmp/solocinema.sqlite
```

## Configuration

Copy `.env.example` to `.env.local` for the app, or `.env` for the collector.

| Variable | Used by | Notes |
| --- | --- | --- |
| `SUPABASE_URL` | app + collector | Supabase project URL |
| `SUPABASE_ANON_KEY` | app | read-only browser key |
| `SUPABASE_SERVICE_ROLE_KEY` | collector | write access — Render only, never the browser |
| `CINEPLEX_SUBSCRIPTION_KEY` | collector | Cineplex's public web-client API key |
| `IMAX_SEATS_API_KEY` | collector | optional override; normally self-discovered from the public ticketing page |
| `DATABASE_URL` | collector | e.g. `sqlite:///tmp/solocinema.sqlite` for local runs |

## Deployment

1. Create a Supabase project and run `supabase/schema.sql` in the SQL editor.
2. Deploy the app to Vercel with `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
3. Create the Render cron job from `render.yaml` and set `SUPABASE_URL` and
   `SUPABASE_SERVICE_ROLE_KEY` in its environment.
