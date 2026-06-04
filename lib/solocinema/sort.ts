import type { ScreeningSummary, ScreeningView } from "./types.ts";

const UNDER_FIVE_LIMIT = 5;
const STALE_AFTER_MINUTES = 90;

export function isUnderFive(screening: ScreeningView) {
  return (
    screening.seatStatus === "available" &&
    screening.inferredOccupied !== null &&
    screening.inferredOccupied < UNDER_FIVE_LIMIT
  );
}

export function isStale(screening: ScreeningView, now = new Date()) {
  const checked = new Date(screening.lastCheckedAt).getTime();
  return now.getTime() - checked > STALE_AFTER_MINUTES * 60 * 1000;
}

export function sortScreenings(
  screenings: readonly ScreeningView[],
  now = new Date()
) {
  return [...screenings].sort((left, right) => {
    const leftUnderFive = isUnderFive(left) ? 0 : 1;
    const rightUnderFive = isUnderFive(right) ? 0 : 1;
    if (leftUnderFive !== rightUnderFive) {
      return leftUnderFive - rightUnderFive;
    }

    const leftStale = isStale(left, now) ? 1 : 0;
    const rightStale = isStale(right, now) ? 1 : 0;
    if (leftStale !== rightStale) {
      return leftStale - rightStale;
    }

    const starts = Date.parse(left.startsAt) - Date.parse(right.startsAt);
    if (starts !== 0) {
      return starts;
    }

    const theater = left.theaterName.localeCompare(right.theaterName);
    if (theater !== 0) {
      return theater;
    }

    return left.movieTitle.localeCompare(right.movieTitle);
  });
}

export function filterScreenings(
  screenings: readonly ScreeningView[],
  options: { showAll: boolean }
) {
  return options.showAll ? [...screenings] : screenings.filter(isUnderFive);
}

export function getNewestCheck(screenings: readonly ScreeningView[]) {
  let newest: string | null = null;
  for (const screening of screenings) {
    if (!newest || Date.parse(screening.lastCheckedAt) > Date.parse(newest)) {
      newest = screening.lastCheckedAt;
    }
  }
  return newest;
}

export function getScreeningSummary(
  screenings: readonly ScreeningView[],
  now = new Date()
): ScreeningSummary {
  return {
    total: screenings.length,
    underFive: screenings.filter(isUnderFive).length,
    unknown: screenings.filter((screening) => screening.inferredOccupied === null)
      .length,
    stale: screenings.filter((screening) => isStale(screening, now)).length
  };
}
