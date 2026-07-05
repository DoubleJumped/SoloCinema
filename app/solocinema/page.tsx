import { getSoloCinemaShowings } from "@/lib/solocinema/data";
import {
  applyScreeningFilters,
  getFilterOptions,
  parseScreeningFilters
} from "@/lib/solocinema/filters";
import {
  filterScreenings,
  getNewestCheck,
  isUnderFive,
  sortScreeningsByTime
} from "@/lib/solocinema/sort";
import { formatRelativeCheck, getReginaDay } from "@/lib/solocinema/time";
import { toBoardRow } from "./board-utils";
import { FilterRail } from "./filter-rail";
import { FlapBoard } from "./flap-board";

export const dynamic = "force-dynamic";

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function SoloCinemaPage({ searchParams }: PageProps) {
  const params = (await searchParams) ?? {};
  const showAll = params.all === "1";
  const filters = parseScreeningFilters(params);
  const now = new Date();
  const screenings = sortScreeningsByTime(await getSoloCinemaShowings());
  const filtered = applyScreeningFilters(screenings, filters);
  const visible = filterScreenings(filtered, { showAll });

  const rows = visible.map(toBoardRow);
  const counts = {
    empty: visible.filter(
      (screening) =>
        screening.seatStatus === "available" &&
        screening.inferredOccupied === 0
    ).length,
    under: visible.filter(isUnderFive).length,
    total: visible.length
  };
  const newestCheck = getNewestCheck(screenings);
  const updatedLabel = `Updated ${
    newestCheck ? formatRelativeCheck(newestCheck, now) : "never"
  }`;
  const options = getFilterOptions(screenings);
  const today = getReginaDay(now.toISOString());
  const tomorrow = getReginaDay(
    new Date(now.getTime() + 24 * 60 * 60 * 1000).toISOString()
  );

  return (
    <main className="wrap">
      <FlapBoard rows={rows} updatedLabel={updatedLabel} counts={counts}>
        <FilterRail
          filters={filters}
          showAll={showAll}
          days={options.days}
          movies={options.movies}
          today={today}
          tomorrow={tomorrow}
        />
      </FlapBoard>
      <footer>SoloCinema — Regina SK</footer>
    </main>
  );
}
