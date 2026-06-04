from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Movie, ScrapeRun, SeatSnapshot, Showing, Theater
from .seat_parser import parse_dom_seats, parse_structured_seats
from .storage import repository_from_url


DEFAULT_DATABASE_URL = "sqlite:///tmp/solocinema.sqlite"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="solocinema-collector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db")
    init_db.add_argument("--database-url", default=DEFAULT_DATABASE_URL)

    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--fixture", required=True)
    dry_run.add_argument("--dom", action="store_true")

    run_fixture = subparsers.add_parser("run-fixture")
    run_fixture.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    run_fixture.add_argument(
        "--fixture",
        default=str(Path(__file__).parents[1] / "fixtures" / "landmark_seatmap.json"),
    )

    probe = subparsers.add_parser("probe-url")
    probe.add_argument("--url", required=True)
    probe.add_argument("--wait-ms", type=int, default=5000)

    args = parser.parse_args(argv)
    if args.command == "init-db":
        repository = repository_from_url(args.database_url)
        repository.init_schema()
        path = getattr(repository, "path", args.database_url)
        print(f"Initialized {path}")
        return 0
    if args.command == "dry-run":
        result = parse_fixture(Path(args.fixture), is_dom=args.dom)
        print(result.model_dump_json(indent=2))
        return 0
    if args.command == "run-fixture":
        run_fixture_collection(args.database_url, Path(args.fixture))
        return 0
    if args.command == "probe-url":
        from .playwright_probe import probe_seat_map, result_to_json

        result = asyncio.run(probe_seat_map(args.url, wait_ms=args.wait_ms))
        print(result_to_json(result))
        return 0
    raise AssertionError(f"Unhandled command {args.command}")


def parse_fixture(path: Path, is_dom: bool = False):
    content = path.read_text(encoding="utf-8")
    if is_dom:
        return parse_dom_seats(content)
    return parse_structured_seats(json.loads(content))


def run_fixture_collection(database_url: str, fixture: Path) -> None:
    repository = repository_from_url(database_url)
    repository.init_schema()
    run_id = repository.start_run(ScrapeRun(chain="Landmark"))

    theater = Theater(
        chain="Landmark",
        name="Landmark Cinemas 8 Regina",
        city="Regina",
        external_id="landmark-regina",
        ticketing_url="https://as.landmarkcinemas.com/showtimes/regina",
    )
    movie = Movie(
        normalized_title="the-quiet-frame",
        source_title="The Quiet Frame",
        rating="PG",
        runtime_minutes=104,
    )
    starts_at = datetime.now(UTC) + timedelta(hours=4)
    showing = Showing(
        theater_external_id=theater.external_id,
        movie_normalized_title=movie.normalized_title,
        starts_at=starts_at,
        format="Laser Ultra",
        auditorium="1",
        ticket_url="https://as.landmarkcinemas.com/showtimes/regina",
        source_id=f"fixture-landmark-{starts_at:%Y%m%d%H%M}",
    )

    try:
        repository.upsert_theater(theater)
        repository.upsert_movie(movie)
        repository.upsert_showing(showing)
        parsed = parse_fixture(fixture)
        repository.insert_snapshot(
            SeatSnapshot(
                showing_source_id=showing.source_id,
                checked_at=datetime.now(UTC),
                inferred_occupied=parsed.inferred_occupied,
                available_seats=parsed.available_seats,
                total_sellable_seats=parsed.total_sellable_seats,
                raw_status=parsed.raw_status,
                confidence=parsed.confidence,
                error_message=parsed.error_message,
            )
        )
        repository.finish_run(run_id, "success", count_checked=1, count_failed=0)
    except Exception:
        repository.finish_run(run_id, "failed", count_checked=1, count_failed=1)
        raise

    rows = repository.list_screenings()
    print(json.dumps([dict(row) for row in rows], indent=2, default=_json_default))


def _json_default(value: Any) -> str:
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
