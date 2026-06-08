# SoloCinema

SoloCinema is a Regina movie tracker for finding major-chain screenings with the
lowest inferred seat occupancy. The repo contains:

- a Next.js `/solocinema` page,
- shared TypeScript sorting/data helpers,
- a Python collector CLI with seat-map parsers,
- a Supabase schema,
- local tests that run without Supabase, Render, or live scraping credentials.

## Current Status

The working Landmark Regina V1 route is Atom Tickets. Landmark's own showtimes
page can block automated Playwright sessions with Akamai Access Denied, but Atom
serves public Landmark Regina showtimes and checkout seat-map fragments without a
login.

What works now:

- `discover-landmark-atom` parses Atom's Landmark Regina theater page.
- `discover-cineplex-southland-atom` experimentally parses Atom's Cineplex
  Southland theater page for disabled, non-ticketable showtime buttons.
- `probe-atom-seatmap` reads an Atom checkout page, fetches its seat-map
  fragments, and infers available versus occupied seats.
- `run-landmark` tries Landmark's own site first, then falls back to Atom when
  Landmark blocks the browser.
- `discover-cineplex` parses Cineplex's Regina showtimes API for Southland
  (`4108`) and Normanview (`4114`) by default.
- `probe-cineplex-seatmap` reads Cineplex layout and preview availability APIs
  and counts available, occupied, and broken seats.
- `run-cineplex` writes Cineplex showings and seat snapshots, and `run-all`
  collects Landmark plus Cineplex in one scheduler command.
- Local SQLite writes and Supabase repository wiring are in place for collector
  dry runs.
- The current collector test suite covers Landmark extraction, Atom discovery,
  Cineplex discovery/counting, seat-map parsing, and local storage.

Current limitations:

- Atom results are inferred from public reserved-seat availability, not official
  sales data.
- Atom returns separate seat-map fragments for price area categories; the parser
  merges those fragments by physical seat id to avoid double-counting.
- Atom has a Cineplex Southland page, but it says ticketing is not available
  there. That page can expose movie/time discovery, but not Atom checkout seat
  maps.
- Cineplex occupancy uses read-only preview availability. It should be treated
  as inferred availability, not official sales data.

## Local Validation

This workspace can be validated with the bundled Codex runtimes:

```bash
/Users/graemewatson/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/*.test.ts
/Users/graemewatson/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s collector/tests
```

The expected git tree after this work is the Landmark/Atom collector source,
tests, and documentation changes. Ignored local artifacts such as `.next/`,
`.venv/`, `node_modules/`, `tmp/`, `*.egg-info`, and `*.tsbuildinfo` are not part
of the commit surface.

For normal development on your machine, install dependencies and run:

```bash
npm install
npm run dev
npm test
```

Then open `http://localhost:3000/solocinema`.

## Environment

Copy `.env.example` to `.env.local` for the Next.js app and to `.env` for the
collector if you want to use the same values there.

The page works without Supabase by showing seeded local data. Once Supabase is
configured, set:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

The collector can also write to local SQLite for tests and dry runs. A URL like
`sqlite:///tmp/solocinema.sqlite` is relative to this workspace; use
`sqlite:////tmp/solocinema.sqlite` for an absolute `/tmp` path.

```bash
/Users/graemewatson/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m collector.solocinema_collector.cli init-db --database-url sqlite:///tmp/solocinema.sqlite
```

For the original live Landmark Playwright spike after Playwright is installed:

```bash
python -m collector.solocinema_collector.cli probe-url \
  --url "https://as.landmarkcinemas.com/showtimes/regina"
```

The probe captures JSON network responses first and falls back to DOM seat
elements. It prints inferred counts without writing to any database.

Landmark's own site can return Akamai Access Denied to automated browsers. The
working V1 path uses Atom Tickets, an official Landmark ticketing partner, for
Landmark Regina showtimes and reserved-seat maps.

To discover Landmark Regina showings through Atom without writing anything:

```bash
python -m collector.solocinema_collector.cli discover-landmark-atom
```

To experiment with Cineplex Southland showtime discovery through Atom:

```bash
python -m collector.solocinema_collector.cli discover-cineplex-southland-atom
```

This currently returns showtimes with `seat_map_url: null` because Atom renders
Southland showtimes as disabled buttons rather than checkout links.

The viable Cineplex path is Cineplex's own ticketing preview flow. Southland is
location id `4108`; Normanview is `4114`. Discover current Cineplex Regina
showings without writing anything:

```bash
python -m collector.solocinema_collector.cli discover-cineplex
```

Under the hood, showtime discovery uses:

```text
GET https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes?language=en&locationId=4108
Ocp-Apim-Subscription-Key: dcdac5601d864addbc2675a2e96cb1f8
```

For each online-enabled, reserved-seating `vistaSessionId`, fetch:

```text
GET https://apis.cineplex.com/prod/ticketing/api/v1/theatre/4108/showtime/{vistaSessionId}/seat-layout
GET https://apis.cineplex.com/prod/ticketing/api/v1/theatre/4108/showtime/{vistaSessionId}/seat-availability?preview=true
Ocp-Apim-Subscription-Key: dcdac5601d864addbc2675a2e96cb1f8
```

Verified on June 6, 2026 against Southland showtimes `263673` and `263674`.
Both returned complete 123-seat layouts and matching availability maps. For
`263673`, availability was `70 Available`, `52 Occupied`, and `1 Broken`; for
`263674`, availability was `110 Available`, `12 Occupied`, and `1 Broken`.
Treat `Available` as open, `Occupied` as taken, and `Broken` as unavailable.
Cineplex's showtime-level `seatsRemaining` can differ slightly from the
seat-map count, so the seat-map availability response should be the source of
truth for occupancy. Re-validated on June 8, 2026 against Southland showtime
`264339`; discovery returned live showings and the seat probe returned a
123-seat layout with `123 Available`.

To probe a single Cineplex seat map:

```bash
python -m collector.solocinema_collector.cli probe-cineplex-seatmap \
  --location-id 4108 \
  --vista-session-id 264339
```

To probe a single Atom checkout seat map:

```bash
python -m collector.solocinema_collector.cli probe-atom-seatmap \
  --url "https://www.atomtickets.com/checkout/{showtime_id}"
```

The Atom probe opens the public checkout page, reads its checkout context, then
loads `/checkout/{showtime_id}/seat-map` for each ticket area category. It
merges those category maps by seat id so Standard and Premiere pricing sections
do not double-count the same physical seat.

To collect Landmark Regina showings and seat snapshots into local SQLite:

```bash
python -m collector.solocinema_collector.cli run-landmark \
  --database-url sqlite:///tmp/solocinema.sqlite
```

`run-landmark` tries Landmark first and automatically falls back to Atom when
Landmark blocks the Playwright browser. Use `--max-showings 3` for a small live
validation run, or `--skip-seat-probe` to verify showtime discovery and database
writes without opening seat-map pages. No Landmark or Atom login is required.
Supabase writes require `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`; browser
reads only use `SUPABASE_URL` and `SUPABASE_ANON_KEY`.

The Cineplex collector has a default observed subscription key for the public
site APIs. If Cineplex rotates it, set `CINEPLEX_SUBSCRIPTION_KEY` in the
collector environment.

To collect Cineplex Regina showings and seat snapshots into local SQLite:

```bash
python -m collector.solocinema_collector.cli run-cineplex \
  --database-url sqlite:///tmp/solocinema.sqlite
```

To collect all supported chains in one run:

```bash
python -m collector.solocinema_collector.cli run-all \
  --database-url sqlite:///tmp/solocinema.sqlite
```

## Supabase Setup

When you are ready to connect Supabase:

1. Create a Supabase project.
2. Open SQL Editor.
3. Run the contents of `supabase/schema.sql`.
4. Copy the project URL and anon key into `.env.local`.
5. For the collector, create a service role key and store it as
   `SUPABASE_SERVICE_ROLE_KEY` in Render only. Do not expose the service key to
   the browser.

## Render Cron Setup

When you are ready to schedule scraping:

1. Create a new Render Cron Job.
2. Point it at this repository.
3. Use Python 3.12.
4. Install command:
   `pip install -e ".[collector]"`
5. Command:
   `python -m collector.solocinema_collector.cli run-all --database-url supabase`
6. Keep `run-fixture` available for smoke tests that exercise writes without
   hitting live theater sites.
7. Add environment variables:
   `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

Render should run every 30-60 minutes during movie hours for V1. The fixture
command is intentionally safe for first deployment because it exercises writes
without hitting live theater sites.
