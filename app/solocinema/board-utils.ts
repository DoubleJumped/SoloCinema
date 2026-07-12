import { formatBoardDate, formatBoardTime } from "@/lib/solocinema/time";
import type { ScreeningView } from "@/lib/solocinema/types";

const THEATER_CODES: Record<string, string> = {
  "Landmark Cinemas 8 Regina": "LANDMARK 8",
  "Cineplex Cinemas Normanview": "NORMANVIEW",
  "Cineplex Cinemas Southland": "SOUTHLAND",
  "Cineplex Odeon Southland Mall": "SOUTHLAND",
  "Rainbow Cinemas Golden Mile": "GOLDEN MILE"
};

const CODE_WIDTH = 13;

export function theaterCode(name: string) {
  const mapped = THEATER_CODES[name];
  if (mapped) {
    return mapped;
  }
  const stripped = name
    .replace(/^(Cineplex (Cinemas|Odeon)|Landmark Cinemas|Rainbow Cinemas)\s+/i, "")
    .toUpperCase();
  if (stripped.length <= CODE_WIDTH) {
    return stripped;
  }
  // cut at a word boundary so codes never end mid-word
  return stripped.slice(0, CODE_WIDTH).replace(/\s+\S*$/, "");
}

export function isSafeTicketUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

export type SeatTier = "green" | "amber" | "red" | "muted";

export function seatTier(occupied: number | null): SeatTier {
  if (occupied === null) {
    return "muted";
  }
  if (occupied < 5) {
    return "green";
  }
  if (occupied < 20) {
    return "amber";
  }
  return "red";
}

const TIER_LABELS: Record<SeatTier, string> = {
  green: "under 5 people",
  amber: "5 to 19 people",
  red: "20 or more people",
  muted: "no seat data"
};

export function seatsLabel(screening: ScreeningView) {
  if (
    screening.inferredOccupied === null ||
    screening.totalSellableSeats === null
  ) {
    return "—";
  }
  return `${screening.inferredOccupied}/${screening.totalSellableSeats}`;
}

export type BoardRow = {
  id: string;
  time: string;
  date: string;
  film: string;
  theatre: string;
  seats: string;
  tier: SeatTier;
  ticketUrl: string;
  aria: string;
};

export function toBoardRow(screening: ScreeningView): BoardRow {
  const tier = seatTier(screening.inferredOccupied);
  const time = formatBoardTime(screening.startsAt);
  const date = formatBoardDate(screening.startsAt);
  return {
    id: screening.id,
    time,
    date,
    film: screening.movieTitle,
    theatre: theaterCode(screening.theaterName),
    seats: seatsLabel(screening),
    tier,
    ticketUrl: screening.ticketUrl,
    aria: `${screening.movieTitle} at ${screening.theaterName}, ${date} ${time}, ${TIER_LABELS[tier]}. Opens the theatre's ticket page.`
  };
}
