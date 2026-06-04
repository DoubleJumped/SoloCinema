import type { ScreeningView } from "./types.ts";

export const sampleScreenings: ScreeningView[] = [
  {
    id: "landmark-regina-1",
    movieTitle: "The Quiet Frame",
    theaterName: "Landmark Cinemas 8 Regina",
    chain: "Landmark",
    startsAt: "2026-06-04T01:15:00.000Z",
    format: "Laser Ultra",
    ticketUrl: "https://as.landmarkcinemas.com/showtimes/regina",
    inferredOccupied: 0,
    availableSeats: 84,
    totalSellableSeats: 84,
    seatStatus: "available",
    confidence: "high",
    lastCheckedAt: "2026-06-03T23:48:00.000Z"
  },
  {
    id: "cineplex-normanview-1",
    movieTitle: "Prairie Signal",
    theaterName: "Cineplex Cinemas Normanview",
    chain: "Cineplex",
    startsAt: "2026-06-04T02:20:00.000Z",
    format: "Regular",
    ticketUrl: "https://www.cineplex.com/theatre/cineplex-cinemas-normanview",
    inferredOccupied: 4,
    availableSeats: 112,
    totalSellableSeats: 116,
    seatStatus: "available",
    confidence: "medium",
    lastCheckedAt: "2026-06-03T23:38:00.000Z"
  },
  {
    id: "landmark-regina-2",
    movieTitle: "Late Show North",
    theaterName: "Landmark Cinemas 8 Regina",
    chain: "Landmark",
    startsAt: "2026-06-04T03:30:00.000Z",
    format: "Recliner",
    ticketUrl: "https://as.landmarkcinemas.com/showtimes/regina",
    inferredOccupied: 18,
    availableSeats: 56,
    totalSellableSeats: 74,
    seatStatus: "available",
    confidence: "high",
    lastCheckedAt: "2026-06-03T23:45:00.000Z"
  },
  {
    id: "cineplex-southland-1",
    movieTitle: "Static Matinee",
    theaterName: "Cineplex Odeon Southland Mall",
    chain: "Cineplex",
    startsAt: "2026-06-04T20:00:00.000Z",
    format: null,
    ticketUrl: "https://www.cineplex.com",
    inferredOccupied: null,
    availableSeats: null,
    totalSellableSeats: null,
    seatStatus: "unavailable",
    confidence: "low",
    lastCheckedAt: "2026-06-03T22:15:00.000Z"
  }
];
