import { formatDayLabel, getReginaDay, getReginaHour } from "./time.ts";
import type { ScreeningView } from "./types.ts";

export const TIME_OF_DAY_OPTIONS = [
  { value: "morning", label: "Morning (before 12 pm)" },
  { value: "afternoon", label: "Afternoon (12-5 pm)" },
  { value: "evening", label: "Evening (5-9 pm)" },
  { value: "late", label: "Late (after 9 pm)" }
] as const;

export type TimeOfDay = (typeof TIME_OF_DAY_OPTIONS)[number]["value"];

export type ChainName = ScreeningView["chain"];

export const ALL_CHAINS: readonly ChainName[] = ["Landmark", "Cineplex", "Galaxy"];

export type ScreeningFilters = {
  movie: string | null;
  theater: string | null;
  day: string | null;
  time: TimeOfDay | null;
  /** null means "all chains"; an empty array means "no chains selected". */
  chains: ChainName[] | null;
};

export type FilterOptions = {
  movies: string[];
  theaters: string[];
  days: { value: string; label: string }[];
};

export const EMPTY_FILTERS: ScreeningFilters = {
  movie: null,
  theater: null,
  day: null,
  time: null,
  chains: null
};

type RawParams = Record<string, string | string[] | undefined>;

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function firstValue(value: string | string[] | undefined) {
  return (Array.isArray(value) ? value[0] : value) ?? null;
}

function isTimeOfDay(value: string | null): value is TimeOfDay {
  return TIME_OF_DAY_OPTIONS.some((option) => option.value === value);
}

function parseChains(value: string | null): ChainName[] | null {
  if (value === "none") {
    return [];
  }
  if (!value) {
    return null;
  }
  const chains = ALL_CHAINS.filter((chain) =>
    value.split(",").includes(chain)
  );
  return chains.length > 0 && chains.length < ALL_CHAINS.length ? chains : null;
}

export function parseScreeningFilters(params: RawParams = {}): ScreeningFilters {
  const day = firstValue(params.day);
  const time = firstValue(params.time);
  return {
    movie: firstValue(params.movie) || null,
    theater: firstValue(params.theater) || null,
    day: day && DAY_PATTERN.test(day) ? day : null,
    time: isTimeOfDay(time) ? time : null,
    chains: parseChains(firstValue(params.chains))
  };
}

export function getTimeOfDay(startsAt: string): TimeOfDay {
  const hour = getReginaHour(startsAt);
  if (hour < 12) {
    return "morning";
  }
  if (hour < 17) {
    return "afternoon";
  }
  if (hour < 21) {
    return "evening";
  }
  return "late";
}

export function hasActiveFilters(filters: ScreeningFilters) {
  return Boolean(
    filters.movie ||
      filters.theater ||
      filters.day ||
      filters.time ||
      filters.chains !== null
  );
}

export function applyScreeningFilters(
  screenings: readonly ScreeningView[],
  filters: ScreeningFilters
) {
  return screenings.filter(
    (screening) =>
      (!filters.movie || screening.movieTitle === filters.movie) &&
      (!filters.theater || screening.theaterName === filters.theater) &&
      (!filters.day || getReginaDay(screening.startsAt) === filters.day) &&
      (!filters.time || getTimeOfDay(screening.startsAt) === filters.time) &&
      (!filters.chains || filters.chains.includes(screening.chain))
  );
}

export function getFilterOptions(
  screenings: readonly ScreeningView[]
): FilterOptions {
  const movies = [...new Set(screenings.map((item) => item.movieTitle))].sort(
    (left, right) => left.localeCompare(right)
  );
  const theaters = [...new Set(screenings.map((item) => item.theaterName))].sort(
    (left, right) => left.localeCompare(right)
  );
  const days = [...new Set(screenings.map((item) => getReginaDay(item.startsAt)))]
    .sort()
    .map((value) => ({ value, label: formatDayLabel(value) }));
  return { movies, theaters, days };
}

export function buildScreeningQuery(
  filters: ScreeningFilters,
  options: { showAll?: boolean } = {}
) {
  const params = new URLSearchParams();
  if (options.showAll) {
    params.set("all", "1");
  }
  if (filters.movie) {
    params.set("movie", filters.movie);
  }
  if (filters.theater) {
    params.set("theater", filters.theater);
  }
  if (filters.day) {
    params.set("day", filters.day);
  }
  if (filters.time) {
    params.set("time", filters.time);
  }
  if (filters.chains !== null) {
    params.set("chains", filters.chains.length ? filters.chains.join(",") : "none");
  }
  return params.toString();
}
