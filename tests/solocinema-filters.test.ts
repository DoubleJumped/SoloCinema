import assert from "node:assert/strict";
import test from "node:test";
import {
  applyScreeningFilters,
  buildScreeningQuery,
  EMPTY_FILTERS,
  getFilterOptions,
  getTimeOfDay,
  hasActiveFilters,
  parseScreeningFilters
} from "../lib/solocinema/filters.ts";
import { getReginaDay } from "../lib/solocinema/time.ts";
import type { ScreeningView } from "../lib/solocinema/types.ts";

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

test("parseScreeningFilters keeps valid values and drops invalid ones", () => {
  assert.deepEqual(
    parseScreeningFilters({
      movie: "The Quiet Frame",
      theater: "Cineplex Cinemas Normanview",
      day: "2026-06-03",
      time: "late"
    }),
    {
      movie: "The Quiet Frame",
      theater: "Cineplex Cinemas Normanview",
      day: "2026-06-03",
      time: "late",
      chains: null
    }
  );

  assert.deepEqual(
    parseScreeningFilters({
      movie: "",
      day: "yesterday",
      time: "brunch"
    }),
    EMPTY_FILTERS
  );

  assert.deepEqual(parseScreeningFilters(), EMPTY_FILTERS);
});

test("parseScreeningFilters takes the first value of repeated params", () => {
  assert.equal(
    parseScreeningFilters({ movie: ["First", "Second"] }).movie,
    "First"
  );
});

test("getReginaDay and getTimeOfDay convert UTC into Regina local buckets", () => {
  // 2026-06-04T03:00Z is 9:00 pm on June 3 in Regina (UTC-6).
  assert.equal(getReginaDay("2026-06-04T03:00:00.000Z"), "2026-06-03");
  assert.equal(getTimeOfDay("2026-06-04T03:00:00.000Z"), "late");

  assert.equal(getTimeOfDay("2026-06-04T15:00:00.000Z"), "morning"); // 9:00 am
  assert.equal(getTimeOfDay("2026-06-04T18:00:00.000Z"), "afternoon"); // 12:00 pm
  assert.equal(getTimeOfDay("2026-06-04T23:30:00.000Z"), "evening"); // 5:30 pm
  assert.equal(getTimeOfDay("2026-06-05T02:59:00.000Z"), "evening"); // 8:59 pm
});

test("applyScreeningFilters filters by movie, theater, day, and time", () => {
  const screenings = [
    screening("a", {
      movieTitle: "The Quiet Frame",
      startsAt: "2026-06-04T01:15:00.000Z" // June 3, 7:15 pm Regina
    }),
    screening("b", {
      movieTitle: "Prairie Signal",
      theaterName: "Cineplex Cinemas Normanview",
      startsAt: "2026-06-04T20:00:00.000Z" // June 4, 2:00 pm Regina
    }),
    screening("c", {
      movieTitle: "The Quiet Frame",
      startsAt: "2026-06-05T03:30:00.000Z" // June 4, 9:30 pm Regina
    })
  ];

  const byMovie = applyScreeningFilters(screenings, {
    ...EMPTY_FILTERS,
    movie: "The Quiet Frame"
  });
  assert.deepEqual(
    byMovie.map((item) => item.id),
    ["a", "c"]
  );

  const byTheater = applyScreeningFilters(screenings, {
    ...EMPTY_FILTERS,
    theater: "Cineplex Cinemas Normanview"
  });
  assert.deepEqual(
    byTheater.map((item) => item.id),
    ["b"]
  );

  const byDay = applyScreeningFilters(screenings, {
    ...EMPTY_FILTERS,
    day: "2026-06-04"
  });
  assert.deepEqual(
    byDay.map((item) => item.id),
    ["b", "c"]
  );

  const byTime = applyScreeningFilters(screenings, {
    ...EMPTY_FILTERS,
    time: "evening"
  });
  assert.deepEqual(
    byTime.map((item) => item.id),
    ["a"]
  );
});

test("applyScreeningFilters stacks multiple filters", () => {
  const screenings = [
    screening("match", {
      movieTitle: "The Quiet Frame",
      startsAt: "2026-06-05T03:30:00.000Z" // June 4, 9:30 pm Regina
    }),
    screening("wrong-movie", {
      movieTitle: "Prairie Signal",
      startsAt: "2026-06-05T03:30:00.000Z"
    }),
    screening("wrong-day", {
      movieTitle: "The Quiet Frame",
      startsAt: "2026-06-06T03:30:00.000Z"
    })
  ];

  const combined = applyScreeningFilters(screenings, {
    movie: "The Quiet Frame",
    theater: "Landmark Cinemas 8 Regina",
    day: "2026-06-04",
    time: "late",
    chains: null
  });
  assert.deepEqual(
    combined.map((item) => item.id),
    ["match"]
  );

  assert.equal(
    applyScreeningFilters(screenings, EMPTY_FILTERS).length,
    screenings.length
  );
});

test("chains filter parses, applies, and round-trips", () => {
  assert.deepEqual(
    parseScreeningFilters({ chains: "Landmark,Cineplex" }).chains,
    ["Landmark", "Cineplex"]
  );
  // full set and garbage both mean "all chains"
  assert.equal(
    parseScreeningFilters({ chains: "Landmark,Cineplex,Galaxy" }).chains,
    null
  );
  assert.equal(parseScreeningFilters({ chains: "IMAX Corp" }).chains, null);
  assert.deepEqual(parseScreeningFilters({ chains: "none" }).chains, []);

  const screenings = [
    screening("landmark"),
    screening("cineplex", {
      theaterName: "Cineplex Cinemas Southland",
      chain: "Cineplex"
    }),
    screening("galaxy", {
      theaterName: "Cineplex Cinemas Normanview",
      chain: "Galaxy"
    })
  ];
  assert.deepEqual(
    applyScreeningFilters(screenings, {
      ...EMPTY_FILTERS,
      chains: ["Cineplex", "Galaxy"]
    }).map((item) => item.id),
    ["cineplex", "galaxy"]
  );
  assert.equal(
    applyScreeningFilters(screenings, { ...EMPTY_FILTERS, chains: [] }).length,
    0
  );

  const withChains = { ...EMPTY_FILTERS, chains: ["Landmark"] as const };
  const query = buildScreeningQuery({
    ...withChains,
    chains: [...withChains.chains]
  });
  assert.deepEqual(
    parseScreeningFilters(Object.fromEntries(new URLSearchParams(query))),
    { ...EMPTY_FILTERS, chains: ["Landmark"] }
  );
  assert.equal(
    buildScreeningQuery({ ...EMPTY_FILTERS, chains: [] }),
    "chains=none"
  );
  assert.equal(hasActiveFilters({ ...EMPTY_FILTERS, chains: ["Landmark"] }), true);
});

test("getFilterOptions dedupes and sorts movies, theaters, and days", () => {
  const options = getFilterOptions([
    screening("a", {
      movieTitle: "Zebra Run",
      startsAt: "2026-06-04T20:00:00.000Z"
    }),
    screening("b", {
      movieTitle: "Apple Orchard",
      theaterName: "Cineplex Cinemas Normanview",
      startsAt: "2026-06-04T22:00:00.000Z"
    }),
    screening("c", {
      movieTitle: "Zebra Run",
      startsAt: "2026-06-04T01:15:00.000Z" // June 3 in Regina
    })
  ]);

  assert.deepEqual(options.movies, ["Apple Orchard", "Zebra Run"]);
  assert.deepEqual(options.theaters, [
    "Cineplex Cinemas Normanview",
    "Landmark Cinemas 8 Regina"
  ]);
  assert.deepEqual(
    options.days.map((day) => day.value),
    ["2026-06-03", "2026-06-04"]
  );
  assert.match(options.days[0].label, /Jun/);
});

test("buildScreeningQuery round-trips through parseScreeningFilters", () => {
  const filters = {
    movie: "The Quiet Frame",
    theater: "Landmark Cinemas 8 Regina",
    day: "2026-06-04",
    time: "evening" as const,
    chains: null
  };
  const query = buildScreeningQuery(filters, { showAll: true });
  const params = Object.fromEntries(new URLSearchParams(query));

  assert.equal(params.all, "1");
  assert.deepEqual(parseScreeningFilters(params), filters);

  assert.equal(buildScreeningQuery(EMPTY_FILTERS), "");
  assert.equal(hasActiveFilters(EMPTY_FILTERS), false);
  assert.equal(hasActiveFilters(filters), true);
});
