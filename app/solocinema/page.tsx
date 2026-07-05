import {
  filterScreenings,
  getNewestCheck,
  getScreeningSummary,
  sortScreenings
} from "@/lib/solocinema/sort";
import {
  applyScreeningFilters,
  buildScreeningQuery,
  getFilterOptions,
  hasActiveFilters,
  parseScreeningFilters
} from "@/lib/solocinema/filters";
import { getSoloCinemaShowings } from "@/lib/solocinema/data";
import { formatRelativeCheck, formatShowtime } from "@/lib/solocinema/time";
import type { ScreeningView } from "@/lib/solocinema/types";
import { FilterBar } from "./filter-bar";

export const dynamic = "force-dynamic";

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function SoloCinemaPage({ searchParams }: PageProps) {
  const params = (await searchParams) ?? {};
  const showAll = params.all === "1";
  const filters = parseScreeningFilters(params);
  const now = new Date();
  const screenings = sortScreenings(await getSoloCinemaShowings(), now);
  const filtered = applyScreeningFilters(screenings, filters);
  const visible = filterScreenings(filtered, { showAll });
  const summary = getScreeningSummary(screenings, now);
  const newestCheck = getNewestCheck(screenings);
  const filterOptions = getFilterOptions(screenings);
  const filtersActive = hasActiveFilters(filters);
  const underFiveQuery = buildScreeningQuery(filters);
  const showAllQuery = buildScreeningQuery(filters, { showAll: true });

  return (
    <main className="solo-page">
      <section className="solo-band">
        <div className="solo-wrap solo-header">
          <div>
            <p className="solo-kicker">Regina screenings</p>
            <h1 className="solo-title">SoloCinema</h1>
            <p className="solo-subtitle">
              Major-chain movie showtimes sorted by lowest inferred occupancy,
              with freshness and confidence shown plainly.
            </p>
          </div>
          <nav className="solo-mode" aria-label="Screening view">
            <a
              href={
                underFiveQuery ? `/solocinema?${underFiveQuery}` : "/solocinema"
              }
              aria-current={!showAll ? "page" : undefined}
            >
              Under 5
            </a>
            <a
              href={`/solocinema?${showAllQuery}`}
              aria-current={showAll ? "page" : undefined}
            >
              Show all
            </a>
          </nav>
        </div>
      </section>

      <div className="solo-wrap">
        <FilterBar filters={filters} options={filterOptions} showAll={showAll} />
      </div>

      <div className="solo-wrap solo-toolbar">
        <span>
          {visible.length} shown of {screenings.length} screenings
          {filtersActive ? " (filters on)" : ""}
        </span>
        <span>
          {summary.underFive} under 5 · {summary.unknown} unknown · last checked{" "}
          {newestCheck ? formatRelativeCheck(newestCheck, now) : "never"}
        </span>
      </div>

      <section className="solo-wrap solo-grid" aria-label="Screenings">
        {visible.length === 0 ? (
          <div className="empty-state">
            {filtersActive
              ? "No screenings match the current filters. Adjust or clear the filters to keep browsing."
              : "No under-5 screenings are available right now. Show all screenings to keep browsing current Regina showtimes."}
          </div>
        ) : (
          visible.map((screening) => (
            <ScreeningCard key={screening.id} screening={screening} now={now} />
          ))
        )}
      </section>
    </main>
  );
}

function ScreeningCard({
  screening,
  now
}: {
  screening: ScreeningView;
  now: Date;
}) {
  const occupancyClass =
    screening.seatStatus === "failed"
      ? "failed"
      : screening.inferredOccupied === null
        ? "unknown"
        : screening.inferredOccupied < 5
          ? "good"
          : "";

  return (
    <article className="screening-card">
      <div className="screening-main">
        <h2 className="screening-title">{screening.movieTitle}</h2>
        <div className="screening-meta">
          <span>{screening.theaterName}</span>
          <span>{formatShowtime(screening.startsAt)}</span>
          {screening.format ? (
            <span className="screening-pill">{screening.format}</span>
          ) : null}
          <span className="screening-pill">{screening.confidence}</span>
          <span className="screening-pill">
            checked {formatRelativeCheck(screening.lastCheckedAt, now)}
          </span>
        </div>
      </div>
      <div className="screening-side">
        <div className={`occupancy ${occupancyClass}`}>
          {formatOccupancy(screening)}
        </div>
        <a className="ticket-link" href={screening.ticketUrl}>
          Tickets
        </a>
      </div>
    </article>
  );
}

function formatOccupancy(screening: ScreeningView) {
  if (screening.seatStatus === "failed") {
    return "seat map failed";
  }
  if (screening.inferredOccupied === null) {
    return screening.seatStatus === "unavailable"
      ? "seat map unavailable"
      : "unknown";
  }
  return `${screening.inferredOccupied} inferred`;
}
