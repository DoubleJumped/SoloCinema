# SoloCinema

SoloCinema is a Regina movie tracker for finding major-chain screenings with the
lowest inferred seat occupancy. The repo contains:

- a Next.js `/solocinema` page,
- shared TypeScript sorting/data helpers,
- a Python collector CLI with seat-map parsers,
- a Supabase schema,
- local tests that run without Supabase, Render, or live scraping credentials.

## Local Validation

This workspace can be validated with the bundled Codex runtimes:

```bash
/Users/graemewatson/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/*.test.ts
/Users/graemewatson/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s collector/tests
```

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

The collector can also write to local SQLite for tests and dry runs:

```bash
/Users/graemewatson/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m collector.solocinema_collector.cli init-db --database-url sqlite:///tmp/solocinema.sqlite
```

For the live seat-map spike after Playwright is installed:

```bash
python -m collector.solocinema_collector.cli probe-url \
  --url "https://as.landmarkcinemas.com/showtimes/regina"
```

The probe captures JSON network responses first and falls back to DOM seat
elements. It prints inferred counts without writing to any database.

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
   `python -m collector.solocinema_collector.cli run-fixture --database-url supabase`
6. Replace `run-fixture` with the live chain collector command after Landmark
   and Cineplex live flows are confirmed.
7. Add environment variables:
   `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

Render should run every 30-60 minutes during movie hours for V1. The fixture
command is intentionally safe for first deployment because it exercises writes
without hitting live theater sites.
