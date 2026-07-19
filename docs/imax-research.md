# Kramer IMAX (Saskatchewan Science Centre) — feasibility research

Date: 2026-07-19. Goal: can SoloCinema track seat occupancy for Regina's IMAX?

**Verdict: yes.** No official API, but the ticketing stack exposes everything we
need through unauthenticated GET requests — and the seat data is actually
*easier* to read than Cineplex's or Landmark's.

## The stack

- Marketing site: `sasksciencecentre.com/showtimes` (Squarespace-ish, weekly
  updated, not machine-friendly — we don't need it).
- Ticketing: `tickets.sasksciencecentre.com` — **Vantix ATMS** (vantix.com), an
  ASP.NET WebForms product used by science centres. Server-rendered HTML, no
  login required for browsing or seat selection.
- Seat maps: hosted by a separate service, **`seats-api.ticketclick.com`**,
  embedded as an iframe. The page ships a public org API key in its HTML
  (`key-ssc-8001482daac3efd0464d67b3`) — same "public key in the JS bundle"
  model as Cineplex, and presumably rotatable the same way (re-scrape
  Selection.aspx to refresh it).

## Discovery flow (all plain GETs, no cookies/tokens needed)

1. **Movies**: `GET /default.aspx?tagid=4` (IMAX Feature Length) and
   `?tagid=3` (IMAX Documentary). Each item links to
   `/DateSelection.aspx?item=<itemId>` with an `<h2>` title.
2. **Showtimes**: `GET /DateSelection.aspx?item=<itemId>` renders links per
   showing:

   ```html
   <a href="Selection.aspx?sch=203852"
      class="ShowTooltip ReservedSeating js-select-date"
      data-schedule="203852"
      data-scheduleDate="Sunday July 19, 2026 - 11:00 AM">
   ```

   Sold-out shows get class `SoldOut` instead of `ReservedSeating`. The page
   defaults to a week/month view with per-day links
   (`?item=X&v=Day&day=D&month=M&year=Y`). There is also an AJAX fragment
   service `/atms/uc/services/Calendar.aspx?item=X&v=All` (returns the same
   markup, worth using if it collapses pagination — verified below).
3. **Seat map** (the occupancy source):

   ```
   GET https://seats-api.ticketclick.com/api/seatingcharts/svg/organization/{apiKey}/atmsSchedule/{scheduleId}
   ```

   Returns a plain SVG (~1 MB). Every seat is a `<circle>`:

   ```html
   <circle seat-id="33703" section-id="1274" seat="1" row="A" section="Main" locked r="7.0000" ... />
   ```

   A seat that is taken/held/blocked carries a bare `locked` attribute;
   an open seat has no `locked`. Count circles = capacity, count locked =
   occupied. That's the whole parser.

   There is also
   `/api/events/mapsections/organization/{apiKey}/atmsSchedule/{id}` which
   returns `{"section":"Main","capacity":154,"available":154,...}` plus
   pricing — **but `available` did not move even for a sold-out show**, so
   treat it as capacity metadata only. The SVG `locked` count is the truth.

## Validation (2026-07-19, "The Odyssey: The IMAX 70mm Experience", item 3608)

| Show (sch id) | Site badge | SVG seats | locked | open |
|---|---|---|---|---|
| Jul 19 11:00 AM (203852) | ReservedSeating | 154 | 153 | 1 |
| Jul 19 3:00 PM (203853) | SoldOut | 154 | 154 | 0 |
| Jul 19 11:00 PM (203854) | ReservedSeating | 154 | 137 | 17 |

Sold-out show = fully locked; tonight's late show 137/154 — internally
consistent. The theatre has one auditorium ("Main", 154 seats incl. 4
wheelchair/companion stalls). `locked` includes house holds, so occupancy is
*inferred*, same caveat as our other sources — the UI already labels it that
way.

## The second key finding: the calendar publishes remaining counts

`Calendar.aspx?item=X&v=All` doesn't just enumerate showtimes — each listing
includes a live count:

```html
<p><strong>Monday, July 20, 2026</strong> - 11:45 AM - 145 Remaining</p>
```

Verified against the SVG for the same showings (1 Remaining ↔ 1 open seat,
0 ↔ sold out, 19 Remaining ↔ 17 open circles — the small gap is
wheelchair-stall accounting). So **one GET per movie yields every future
showtime with availability**, and the SVG is only needed when we want the
precise per-seat count.

This also solves general admission: the IMAX documentaries (Call of the
Dolphins, Lost Wolves of Yellowstone) have **no seat map** (the seats API
404s for them) because they're GA — but the calendar still reports
"145 Remaining", and the room is always the same 154-seat auditorium, so
occupancy is inferred as `154 - remaining` at low confidence.

## Caveats

- `locked` conflates sold + held + house-blocked seats. Fine for "how empty is
  this showing", which is the product question.
- GA remaining-based occupancy can overcount if the venue holds seats back
  from online sale; snapshots from that path are marked `confidence: low`
  (seat-map snapshots are `medium`).
- The seats API key is embedded in Selection.aspx and could rotate like
  Cineplex's. The collector re-scrapes it from a public Selection.aspx page
  each run (env `IMAX_SEATS_API_KEY` overrides; a hardcoded last-known value
  is the final fallback), so a rotation self-heals with no deploy.
- The SVG is ~1 MB per showing, so the collector only probes seat maps for
  showings starting within `--probe-days` (default 2); everything further out
  gets the free calendar-based snapshot.
- Showtimes are published weekly; some days have zero shows.

## What was built

- `collector/solocinema_collector/imax.py` — discovery via tagid=18 listing +
  per-item `Calendar v=All`, seat-map probe, calendar fallback, and
  `run_imax_collection` mirroring the Cineplex module. Theatre is stored as
  chain `Other` / external id `kramer-imax` (no Supabase schema change —
  the check constraint already allows `Other`).
- CLI: `discover-imax`, `probe-imax-seatmap --sch <id>`, `run-imax`, and
  IMAX included in `run-all`.
- Frontend: `IMAX` is a fourth chain — `normalizeChain` maps the Kramer
  theatre name to it (same pattern as Galaxy), it gets a filter chip, the
  board shows `KRAMER IMAX`, and sample data includes two IMAX rows.
- `render.yaml`: cron window extended (see below).
- Tests: `collector/tests/test_imax.py` on trimmed real fixtures; frontend
  chain tests updated for the four-chain set.

## Try it locally

```bash
# collector against the live site (read-only, ~6 GETs):
source .venv/bin/activate   # or: pip install -e ".[collector]"
python -m collector.solocinema_collector.cli discover-imax --max-showings 8
python -m collector.solocinema_collector.cli probe-imax-seatmap --sch <schedule_id>
python -m collector.solocinema_collector.cli run-imax --database-url sqlite:///tmp/imax.sqlite

# UI with bundled sample data (note: .env.local points at prod Supabase, so
# blank the URL to force sample mode):
SUPABASE_URL= npm run dev    # http://localhost:3000/solocinema?all=1
```

On the live site, the IMAX rows appear as soon as the Render cron (with this
branch deployed) writes its first snapshots; no schema migration is needed.

## Cron-timing impact

The old window was every 15 min, 2:00pm-9:45pm Regina (evening-weighted for
Cineplex/Landmark). Kramer IMAX is **matinee-heavy** — documentaries at
11:45am/1:00pm, features from 11:00am — and its late Odyssey shows start at
10:05/11:00pm. `render.yaml` now runs every 15 min from **10:00am to 11:45pm
Regina** (`*/15 16-23,0-5 * * *` UTC): 56 runs/day instead of 32. Each run
adds ~6 IMAX HTTP requests (1 listing + ~5 calendars) plus one ~1 MB SVG per
near-term reserved showing.
