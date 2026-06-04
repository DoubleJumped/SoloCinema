import {
  filterScreenings,
  getNewestCheck,
  getScreeningSummary,
  sortScreenings
} from "@/lib/solocinema/sort";
import { getSoloCinemaShowings } from "@/lib/solocinema/data";
import { formatRelativeCheck, formatShowtime } from "@/lib/solocinema/time";
import type { ScreeningView } from "@/lib/solocinema/types";

export const dynamic = "force-dynamic";

type PageProps = {
  searchParams?: Promise<{ all?: string }> | { all?: string };
};

export default async function SoloCinemaPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const showAll = params?.all === "1";
  const now = new Date();
  const screenings = sortScreenings(await getSoloCinemaShowings(), now);
  const visible = filterScreenings(screenings, { showAll });
  const summary = getScreeningSummary(screenings, now);
  const newestCheck = getNewestCheck(screenings);

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
            <a href="/solocinema" aria-current={!showAll ? "page" : undefined}>
              Under 5
            </a>
            <a
              href="/solocinema?all=1"
              aria-current={showAll ? "page" : undefined}
            >
              Show all
            </a>
          </nav>
        </div>
      </section>

      <div className="solo-wrap solo-toolbar">
        <span>
          {visible.length} shown of {screenings.length} screenings
        </span>
        <span>
          {summary.underFive} under 5 · {summary.unknown} unknown · last checked{" "}
          {newestCheck ? formatRelativeCheck(newestCheck, now) : "never"}
        </span>
      </div>

      <section className="solo-wrap solo-grid" aria-label="Screenings">
        {visible.length === 0 ? (
          <div className="empty-state">
            No under-5 screenings are available right now. Show all screenings to
            keep browsing current Regina showtimes.
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
