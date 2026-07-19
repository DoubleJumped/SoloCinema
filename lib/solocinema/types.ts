export type SeatStatus = "available" | "unknown" | "failed" | "unavailable";

export type Confidence = "high" | "medium" | "low";

export type ScreeningView = {
  id: string;
  movieTitle: string;
  theaterName: string;
  chain: "Landmark" | "Cineplex" | "Galaxy" | "IMAX";
  startsAt: string;
  format: string | null;
  ticketUrl: string;
  inferredOccupied: number | null;
  availableSeats: number | null;
  totalSellableSeats: number | null;
  seatStatus: SeatStatus;
  confidence: Confidence;
  lastCheckedAt: string;
};

export type ScreeningSummary = {
  total: number;
  underFive: number;
  unknown: number;
  stale: number;
};
