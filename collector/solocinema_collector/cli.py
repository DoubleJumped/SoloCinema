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

    discover_landmark = subparsers.add_parser("discover-landmark")
    discover_landmark.add_argument("--url", default="https://as.landmarkcinemas.com/showtimes/regina")
    discover_landmark.add_argument("--wait-ms", type=int, default=5000)
    discover_landmark.add_argument("--max-showings", type=int)

    discover_landmark_atom = subparsers.add_parser("discover-landmark-atom")
    discover_landmark_atom.add_argument(
        "--url", default="https://www.atomtickets.com/theaters/landmark-cinemas-regina/49885"
    )
    discover_landmark_atom.add_argument("--max-showings", type=int)

    discover_cineplex_southland_atom = subparsers.add_parser("discover-cineplex-southland-atom")
    discover_cineplex_southland_atom.add_argument(
        "--url",
        default="https://www.atomtickets.com/theaters/cineplex-odeon-southland-mall-cinemas/6446",
    )
    discover_cineplex_southland_atom.add_argument("--max-showings", type=int)

    discover_cineplex = subparsers.add_parser("discover-cineplex")
    discover_cineplex.add_argument(
        "--location-id",
        action="append",
        dest="location_ids",
        help="Cineplex location id. Can be passed more than once; defaults to Regina locations.",
    )
    discover_cineplex.add_argument("--max-showings", type=int)

    probe_cineplex = subparsers.add_parser("probe-cineplex-seatmap")
    probe_cineplex.add_argument("--location-id", required=True)
    probe_cineplex.add_argument("--vista-session-id", required=True)

    probe_atom = subparsers.add_parser("probe-atom-seatmap")
    probe_atom.add_argument("--url", required=True)

    run_landmark = subparsers.add_parser("run-landmark")
    run_landmark.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    run_landmark.add_argument("--url", default="https://as.landmarkcinemas.com/showtimes/regina")
    run_landmark.add_argument("--wait-ms", type=int, default=5000)
    run_landmark.add_argument("--max-showings", type=int)
    run_landmark.add_argument(
        "--days-ahead",
        type=int,
        default=7,
        help="Discover showings this many days out, starting today (Regina time).",
    )
    run_landmark.add_argument(
        "--probe-days",
        type=int,
        default=2,
        help="Open seat maps only for showings within the first N days.",
    )
    run_landmark.add_argument(
        "--skip-seat-probe",
        action="store_true",
        help="Write discovered showings with unknown snapshots without opening seat maps.",
    )

    run_cineplex = subparsers.add_parser("run-cineplex")
    run_cineplex.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    run_cineplex.add_argument(
        "--location-id",
        action="append",
        dest="location_ids",
        help="Cineplex location id. Can be passed more than once; defaults to Regina locations.",
    )
    run_cineplex.add_argument("--max-showings", type=int)
    run_cineplex.add_argument(
        "--skip-seat-probe",
        action="store_true",
        help="Write discovered showings with unknown snapshots without opening seat maps.",
    )

    run_all = subparsers.add_parser("run-all")
    run_all.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    run_all.add_argument("--wait-ms", type=int, default=5000)
    run_all.add_argument("--max-showings-per-chain", type=int)
    run_all.add_argument(
        "--days-ahead",
        type=int,
        default=7,
        help="Discover Landmark showings this many days out, starting today (Regina time).",
    )
    run_all.add_argument(
        "--probe-days",
        type=int,
        default=2,
        help="Open Landmark seat maps only for showings within the first N days.",
    )
    run_all.add_argument(
        "--skip-seat-probe",
        action="store_true",
        help="Write discovered showings with unknown snapshots without opening seat maps.",
    )

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
    if args.command == "discover-landmark":
        from .landmark import discover_landmark_showings, showings_to_json

        try:
            showings = asyncio.run(
                discover_landmark_showings(args.url, wait_ms=args.wait_ms)
            )
        except RuntimeError as error:
            parser.exit(1, f"error: {error}\n")
        if args.max_showings is not None:
            showings = showings[: args.max_showings]
        print(showings_to_json(showings))
        return 0
    if args.command == "discover-landmark-atom":
        from .atom import discover_atom_showings
        from .landmark import landmark_showing_from_atom, showings_to_json

        showings = [landmark_showing_from_atom(showing) for showing in discover_atom_showings(args.url)]
        if args.max_showings is not None:
            showings = showings[: args.max_showings]
        print(showings_to_json(showings))
        return 0
    if args.command == "discover-cineplex-southland-atom":
        from .atom import discover_atom_showings
        from .landmark import showings_to_json

        showings = discover_atom_showings(
            args.url,
            source_prefix="cineplex-southland",
            include_unticketed=True,
        )
        if args.max_showings is not None:
            showings = showings[: args.max_showings]
        print(showings_to_json(showings))
        return 0
    if args.command == "discover-cineplex":
        from .cineplex import (
            CINEPLEX_REGINA_THEATERS,
            discover_cineplex_showings,
            showings_to_json,
        )

        showings = []
        for location_id in args.location_ids or list(CINEPLEX_REGINA_THEATERS):
            showings.extend(discover_cineplex_showings(location_id))
        if args.max_showings is not None:
            showings = showings[: args.max_showings]
        print(showings_to_json(showings))
        return 0
    if args.command == "probe-cineplex-seatmap":
        from .cineplex import (
            CINEPLEX_SUBSCRIPTION_KEY,
            parse_cineplex_seat_responses,
            _open_json,
            _seat_availability_url,
            _seat_layout_url,
        )
        from .playwright_probe import result_to_json

        layout = _open_json(
            _seat_layout_url(args.location_id, args.vista_session_id),
            subscription_key=CINEPLEX_SUBSCRIPTION_KEY,
        )
        availability = _open_json(
            _seat_availability_url(args.location_id, args.vista_session_id),
            subscription_key=CINEPLEX_SUBSCRIPTION_KEY,
        )
        print(result_to_json(parse_cineplex_seat_responses(layout, availability)))
        return 0
    if args.command == "probe-atom-seatmap":
        from .atom import probe_atom_checkout_seat_map
        from .playwright_probe import result_to_json

        print(result_to_json(probe_atom_checkout_seat_map(args.url)))
        return 0
    if args.command == "run-landmark":
        from .landmark import run_landmark_collection, summary_to_json

        try:
            summary = run_landmark_collection(
                database_url=args.database_url,
                showtimes_url=args.url,
                wait_ms=args.wait_ms,
                max_showings=args.max_showings,
                probe_seats=not args.skip_seat_probe,
                days_ahead=args.days_ahead,
                probe_days=args.probe_days,
            )
        except RuntimeError as error:
            parser.exit(1, f"error: {error}\n")
        print(summary_to_json(summary))
        return 0
    if args.command == "run-cineplex":
        from .cineplex import run_cineplex_collection, summary_to_json

        summary = run_cineplex_collection(
            database_url=args.database_url,
            location_ids=args.location_ids,
            max_showings=args.max_showings,
            probe_seats=not args.skip_seat_probe,
        )
        print(summary_to_json(summary))
        return 0
    if args.command == "run-all":
        from dataclasses import asdict

        from .cineplex import run_cineplex_collection
        from .landmark import run_landmark_collection

        # One chain failing must not stop the other from collecting.
        output: dict[str, Any] = {}
        errors: dict[str, str] = {}
        try:
            landmark_summary = run_landmark_collection(
                database_url=args.database_url,
                wait_ms=args.wait_ms,
                max_showings=args.max_showings_per_chain,
                probe_seats=not args.skip_seat_probe,
                days_ahead=args.days_ahead,
                probe_days=args.probe_days,
            )
            output["landmark"] = asdict(landmark_summary)
        except Exception as error:
            errors["landmark"] = f"{type(error).__name__}: {error}"
        try:
            cineplex_summary = run_cineplex_collection(
                database_url=args.database_url,
                max_showings=args.max_showings_per_chain,
                probe_seats=not args.skip_seat_probe,
            )
            output["cineplex"] = asdict(cineplex_summary)
        except Exception as error:
            errors["cineplex"] = f"{type(error).__name__}: {error}"
        if errors:
            output["errors"] = errors
        print(json.dumps(output, indent=2))
        return 1 if errors else 0
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
