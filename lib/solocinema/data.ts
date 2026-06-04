import { sampleScreenings } from "./sample.ts";
import type { Confidence, ScreeningView, SeatStatus } from "./types.ts";

type SupabaseScreeningRow = {
  showing_id: string;
  movie_title: string;
  theater_name: string;
  chain: string;
  starts_at: string;
  format: string | null;
  ticket_url: string;
  inferred_occupied: number | null;
  available_seats: number | null;
  total_sellable_seats: number | null;
  raw_status: string | null;
  confidence: string | null;
  checked_at: string | null;
};

export async function getSoloCinemaShowings(): Promise<ScreeningView[]> {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseKey) {
    return sampleScreenings;
  }

  const response = await fetch(
    `${supabaseUrl}/rest/v1/solocinema_screenings?select=*&order=starts_at.asc`,
    {
      headers: {
        apikey: supabaseKey,
        Authorization: `Bearer ${supabaseKey}`
      },
      cache: "no-store"
    }
  );

  if (!response.ok) {
    return sampleScreenings;
  }

  const rows = (await response.json()) as SupabaseScreeningRow[];
  return rows.map(mapSupabaseRow);
}

function mapSupabaseRow(row: SupabaseScreeningRow): ScreeningView {
  return {
    id: row.showing_id,
    movieTitle: row.movie_title,
    theaterName: row.theater_name,
    chain: normalizeChain(row.chain),
    startsAt: row.starts_at,
    format: row.format,
    ticketUrl: row.ticket_url,
    inferredOccupied: row.inferred_occupied,
    availableSeats: row.available_seats,
    totalSellableSeats: row.total_sellable_seats,
    seatStatus: normalizeSeatStatus(row.raw_status),
    confidence: normalizeConfidence(row.confidence),
    lastCheckedAt: row.checked_at ?? row.starts_at
  };
}

function normalizeChain(chain: string): ScreeningView["chain"] {
  if (chain === "Landmark" || chain === "Cineplex") {
    return chain;
  }
  return "Other";
}

function normalizeSeatStatus(status: string | null): SeatStatus {
  if (
    status === "available" ||
    status === "unknown" ||
    status === "failed" ||
    status === "unavailable"
  ) {
    return status;
  }
  return "unknown";
}

function normalizeConfidence(confidence: string | null): Confidence {
  if (
    confidence === "high" ||
    confidence === "medium" ||
    confidence === "low"
  ) {
    return confidence;
  }
  return "low";
}
