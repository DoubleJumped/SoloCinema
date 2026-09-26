import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { getSoloCinemaShowings } from "../lib/solocinema/data.ts";

const realFetch = globalThis.fetch;
const realError = console.error;

beforeEach(() => {
  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_ANON_KEY = "anon";
  console.error = () => {};
});

afterEach(() => {
  globalThis.fetch = realFetch;
  console.error = realError;
  delete process.env.SUPABASE_URL;
  delete process.env.SUPABASE_ANON_KEY;
});

test("serves sample screenings only when Supabase isn't configured", async () => {
  delete process.env.SUPABASE_URL;

  const result = await getSoloCinemaShowings();

  assert.equal(result.source, "sample");
  assert.ok(result.screenings.length > 0);
});

test("maps live rows", async () => {
  globalThis.fetch = async () =>
    Response.json([
      {
        showing_id: "1",
        movie_title: "Film",
        theater_name: "Cineplex Cinemas Normanview",
        chain: "Cineplex",
        starts_at: "2026-09-26T02:00:00Z",
        format: null,
        ticket_url: "https://www.cineplex.com/",
        inferred_occupied: 3,
        available_seats: 90,
        total_sellable_seats: 93,
        raw_status: "available",
        confidence: "high",
        checked_at: "2026-09-26T01:00:00Z"
      }
    ]);

  const result = await getSoloCinemaShowings();

  assert.equal(result.source, "live");
  assert.equal(result.screenings[0].chain, "Galaxy");
  assert.equal(result.screenings[0].inferredOccupied, 3);
});

test("reports unavailable instead of sample data on an error response", async () => {
  globalThis.fetch = async () => new Response("nope", { status: 503 });

  const result = await getSoloCinemaShowings();

  assert.deepEqual(result, { screenings: [], source: "unavailable" });
});

test("reports unavailable when the request throws", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };

  const result = await getSoloCinemaShowings();

  assert.deepEqual(result, { screenings: [], source: "unavailable" });
});
