"use client";

import { useRouter } from "next/navigation";
import {
  ALL_CHAINS,
  buildScreeningQuery,
  EMPTY_FILTERS,
  hasActiveFilters,
  type ChainName,
  type ScreeningFilters
} from "@/lib/solocinema/filters";

type FilterRailProps = {
  filters: ScreeningFilters;
  showAll: boolean;
  days: { value: string; label: string }[];
  movies: string[];
  today: string;
  tomorrow: string;
};

export function FilterRail({
  filters,
  showAll,
  days,
  movies,
  today,
  tomorrow
}: FilterRailProps) {
  const router = useRouter();
  const activeChains = filters.chains ?? [...ALL_CHAINS];

  function navigate(next: ScreeningFilters, nextShowAll = showAll) {
    const query = buildScreeningQuery(next, { showAll: nextShowAll });
    router.replace(query ? `/solocinema?${query}` : "/solocinema", {
      scroll: false
    });
  }

  function setDay(day: string | null) {
    navigate({ ...filters, day });
  }

  function toggleChain(chain: ChainName) {
    const next = activeChains.includes(chain)
      ? activeChains.filter((item) => item !== chain)
      : [...activeChains, chain];
    navigate({
      ...filters,
      chains: next.length === ALL_CHAINS.length ? null : next
    });
  }

  function dayLabel(day: { value: string; label: string }) {
    if (day.value === today) {
      return `${day.label} · Tonight`;
    }
    if (day.value === tomorrow) {
      return `${day.label} · Tomorrow`;
    }
    return day.label;
  }

  return (
    <nav className="filters" aria-label="Filter screenings">
      <div className="fgroup" role="group" aria-label="When">
        <button
          type="button"
          className="switch time"
          aria-pressed={filters.day === today}
          onClick={() => setDay(filters.day === today ? null : today)}
        >
          <span className="led"></span>Tonight
        </button>
        <button
          type="button"
          className="switch time"
          aria-pressed={filters.day === tomorrow}
          onClick={() => setDay(filters.day === tomorrow ? null : tomorrow)}
        >
          <span className="led"></span>Tomorrow
        </button>
        <select
          className={`fselect${filters.day ? " active" : ""}`}
          aria-label="Date"
          value={filters.day ?? "all"}
          onChange={(event) =>
            setDay(event.target.value === "all" ? null : event.target.value)
          }
        >
          <option value="all">All dates</option>
          {days.map((day) => (
            <option key={day.value} value={day.value}>
              {dayLabel(day)}
            </option>
          ))}
        </select>
      </div>
      <div className="divider" aria-hidden="true"></div>
      <div className="fgroup" role="group" aria-label="Chain">
        {ALL_CHAINS.map((chain) => (
          <button
            key={chain}
            type="button"
            className="switch chain"
            aria-pressed={activeChains.includes(chain)}
            onClick={() => toggleChain(chain)}
          >
            <span className="led"></span>
            {chain}
          </button>
        ))}
      </div>
      <div className="divider" aria-hidden="true"></div>
      <div className="fgroup" aria-label="Film">
        <select
          className={`fselect${filters.movie ? " active" : ""}`}
          aria-label="Film"
          value={filters.movie ?? "all"}
          onChange={(event) =>
            navigate({
              ...filters,
              movie: event.target.value === "all" ? null : event.target.value
            })
          }
        >
          <option value="all">All films</option>
          {movies.map((movie) => (
            <option key={movie} value={movie}>
              {movie}
            </option>
          ))}
        </select>
      </div>
      <div className="divider" aria-hidden="true"></div>
      <div className="fgroup" role="group" aria-label="Occupancy">
        <button
          type="button"
          className="switch occupancy"
          aria-pressed={!showAll}
          onClick={() => navigate(filters, !showAll)}
        >
          <span className="led"></span>Under 5 Seats Sold
        </button>
      </div>
      <div className="divider" aria-hidden="true"></div>
      <button
        type="button"
        className="switch reset"
        disabled={!hasActiveFilters(filters) && !showAll}
        onClick={() => navigate({ ...EMPTY_FILTERS }, false)}
      >
        Reset
      </button>
    </nav>
  );
}
