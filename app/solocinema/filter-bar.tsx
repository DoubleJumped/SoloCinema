"use client";

import { useRouter } from "next/navigation";
import {
  buildScreeningQuery,
  EMPTY_FILTERS,
  hasActiveFilters,
  TIME_OF_DAY_OPTIONS,
  type FilterOptions,
  type ScreeningFilters
} from "@/lib/solocinema/filters";

type FilterBarProps = {
  filters: ScreeningFilters;
  options: FilterOptions;
  showAll: boolean;
};

export function FilterBar({ filters, options, showAll }: FilterBarProps) {
  const router = useRouter();

  function navigate(next: ScreeningFilters) {
    const query = buildScreeningQuery(next, { showAll });
    router.replace(query ? `/solocinema?${query}` : "/solocinema", {
      scroll: false
    });
  }

  function update(key: keyof ScreeningFilters, value: string) {
    navigate({ ...filters, [key]: value || null });
  }

  return (
    <form
      className="solo-filters"
      aria-label="Screening filters"
      onSubmit={(event) => event.preventDefault()}
    >
      <label className="solo-filter">
        <span>Movie</span>
        <select
          value={filters.movie ?? ""}
          onChange={(event) => update("movie", event.target.value)}
        >
          <option value="">All movies</option>
          {options.movies.map((movie) => (
            <option key={movie} value={movie}>
              {movie}
            </option>
          ))}
        </select>
      </label>

      <label className="solo-filter">
        <span>Theater</span>
        <select
          value={filters.theater ?? ""}
          onChange={(event) => update("theater", event.target.value)}
        >
          <option value="">All theaters</option>
          {options.theaters.map((theater) => (
            <option key={theater} value={theater}>
              {theater}
            </option>
          ))}
        </select>
      </label>

      <label className="solo-filter">
        <span>Day</span>
        <select
          value={filters.day ?? ""}
          onChange={(event) => update("day", event.target.value)}
        >
          <option value="">All days</option>
          {options.days.map((day) => (
            <option key={day.value} value={day.value}>
              {day.label}
            </option>
          ))}
        </select>
      </label>

      <label className="solo-filter">
        <span>Time</span>
        <select
          value={filters.time ?? ""}
          onChange={(event) => update("time", event.target.value)}
        >
          <option value="">Any time</option>
          {TIME_OF_DAY_OPTIONS.map((slot) => (
            <option key={slot.value} value={slot.value}>
              {slot.label}
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        className="solo-clear"
        onClick={() => navigate(EMPTY_FILTERS)}
        disabled={!hasActiveFilters(filters)}
      >
        Clear filters
      </button>
    </form>
  );
}
