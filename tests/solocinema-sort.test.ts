import assert from "node:assert/strict";
import test from "node:test";
import {
  filterScreenings,
  getScreeningSummary,
  isStale,
  sortScreenings
} from "../lib/solocinema/sort.ts";
import type { ScreeningView } from "../lib/solocinema/types.ts";

const now = new Date("2026-06-04T00:00:00.000Z");

function screening(
  id: string,
  overrides: Partial<ScreeningView> = {}
): ScreeningView {
  return {
    id,
    movieTitle: `Movie ${id}`,
    theaterName: "Landmark Cinemas 8 Regina",
    chain: "Landmark",
    startsAt: "2026-06-04T03:00:00.000Z",
    format: null,
    ticketUrl: "https://example.test",
    inferredOccupied: 12,
    availableSeats: 40,
    totalSellableSeats: 52,
    seatStatus: "available",
    confidence: "high",
    lastCheckedAt: "2026-06-03T23:40:00.000Z",
    ...overrides
  };
}

test("sortScreenings puts fresh under-5 screenings first, then soonest", () => {
  const sorted = sortScreenings(
    [
      screening("busy", { inferredOccupied: 9 }),
      screening("later-empty", {
        inferredOccupied: 0,
        startsAt: "2026-06-04T04:00:00.000Z"
      }),
      screening("soon-empty", {
        inferredOccupied: 4,
        startsAt: "2026-06-04T02:00:00.000Z"
      })
    ],
    now
  );

  assert.deepEqual(
    sorted.map((item) => item.id),
    ["soon-empty", "later-empty", "busy"]
  );
});

test("sortScreenings avoids promoting stale under-5 data over fresh data", () => {
  const sorted = sortScreenings(
    [
      screening("stale-empty", {
        inferredOccupied: 1,
        lastCheckedAt: "2026-06-03T20:00:00.000Z"
      }),
      screening("fresh-empty", {
        inferredOccupied: 2,
        startsAt: "2026-06-04T05:00:00.000Z"
      })
    ],
    now
  );

  assert.equal(sorted[0].id, "fresh-empty");
});

test("filterScreenings supports under-5 and show-all modes", () => {
  const screenings = [
    screening("empty", { inferredOccupied: 0 }),
    screening("unknown", { inferredOccupied: null, seatStatus: "unknown" }),
    screening("busy", { inferredOccupied: 10 })
  ];

  assert.deepEqual(
    filterScreenings(screenings, { showAll: false }).map((item) => item.id),
    ["empty"]
  );
  assert.equal(filterScreenings(screenings, { showAll: true }).length, 3);
});

test("summary counts unknown and stale screenings", () => {
  const summary = getScreeningSummary(
    [
      screening("empty", { inferredOccupied: 0 }),
      screening("unknown", { inferredOccupied: null, seatStatus: "unknown" }),
      screening("stale", { lastCheckedAt: "2026-06-03T20:00:00.000Z" })
    ],
    now
  );

  assert.deepEqual(summary, {
    total: 3,
    underFive: 1,
    unknown: 1,
    stale: 1
  });
  assert.equal(
    isStale(screening("fresh", { lastCheckedAt: "2026-06-03T23:00:00.000Z" }), now),
    false
  );
});
