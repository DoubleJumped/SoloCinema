from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from collector.solocinema_collector.models import Movie, SeatSnapshot, Showing, Theater
from collector.solocinema_collector.storage import SQLiteRepository, SupabaseRepository


class SQLiteRepositoryTests(unittest.TestCase):
    def test_writes_showing_snapshot_and_latest_screening(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'solocinema.sqlite'}"
            repository = SQLiteRepository(database_url)
            repository.init_schema()

            repository.upsert_theater(
                Theater(
                    chain="Landmark",
                    name="Landmark Cinemas 8 Regina",
                    city="Regina",
                    external_id="landmark-regina",
                    ticketing_url="https://as.landmarkcinemas.com/showtimes/regina",
                )
            )
            repository.upsert_movie(
                Movie(
                    normalized_title="the-quiet-frame",
                    source_title="The Quiet Frame",
                )
            )
            repository.upsert_showing(
                Showing(
                    theater_external_id="landmark-regina",
                    movie_normalized_title="the-quiet-frame",
                    starts_at=datetime(2026, 6, 4, 1, 15, tzinfo=timezone.utc),
                    ticket_url="https://as.landmarkcinemas.com/showtimes/regina",
                    source_id="landmark-regina-the-quiet-frame-202606040115",
                    format="Laser Ultra",
                )
            )
            snapshot_id = repository.insert_snapshot(
                SeatSnapshot(
                    showing_source_id="landmark-regina-the-quiet-frame-202606040115",
                    checked_at=datetime(2026, 6, 3, 23, 45, tzinfo=timezone.utc),
                    inferred_occupied=2,
                    available_seats=80,
                    total_sellable_seats=82,
                    raw_status="available",
                    confidence="high",
                )
            )

            rows = repository.list_screenings()
            self.assertGreater(snapshot_id, 0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["movie_title"], "The Quiet Frame")
            self.assertEqual(rows[0]["inferred_occupied"], 2)

    def test_prune_keeps_final_counts_for_finished_showings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'solocinema.sqlite'}"
            repository = SQLiteRepository(database_url)
            repository.init_schema()

            repository.upsert_theater(
                Theater(
                    chain="Landmark",
                    name="Landmark Cinemas 8 Regina",
                    city="Regina",
                    external_id="landmark-regina",
                    ticketing_url="https://as.landmarkcinemas.com/showtimes/regina",
                )
            )
            repository.upsert_movie(
                Movie(
                    normalized_title="the-quiet-frame",
                    source_title="The Quiet Frame",
                )
            )

            now = datetime.now(timezone.utc)

            def add_showing(source_id: str, starts_at: datetime) -> None:
                repository.upsert_showing(
                    Showing(
                        theater_external_id="landmark-regina",
                        movie_normalized_title="the-quiet-frame",
                        starts_at=starts_at,
                        ticket_url="https://as.landmarkcinemas.com/showtimes/regina",
                        source_id=source_id,
                    )
                )

            def add_snapshot(
                source_id: str, checked_at: datetime, occupied: int | None
            ) -> int:
                return repository.insert_snapshot(
                    SeatSnapshot(
                        showing_source_id=source_id,
                        checked_at=checked_at,
                        inferred_occupied=occupied,
                        available_seats=82 - occupied if occupied is not None else None,
                        total_sellable_seats=82 if occupied is not None else None,
                        raw_status="available" if occupied is not None else "failed",
                        confidence="high" if occupied is not None else "low",
                    )
                )

            # finished two days ago: three timed snapshots, then a failed probe
            add_showing("finished", now - timedelta(days=2))
            add_snapshot("finished", now - timedelta(days=2, hours=3), 1)
            add_snapshot("finished", now - timedelta(days=2, hours=2), 4)
            final_with_data = add_snapshot(
                "finished", now - timedelta(days=2, hours=1), 9
            )
            failed_after = add_snapshot("finished", now - timedelta(days=2, minutes=30), None)

            # upcoming tonight: history must be untouched
            add_showing("upcoming", now + timedelta(hours=4))
            upcoming_ids = {
                add_snapshot("upcoming", now - timedelta(hours=2), 0),
                add_snapshot("upcoming", now - timedelta(hours=1), 3),
            }

            deleted = repository.prune_snapshots()
            self.assertEqual(deleted, 2)

            with repository.connect() as connection:
                kept = {
                    row["id"]: row["inferred_occupied"]
                    for row in connection.execute(
                        "select id, inferred_occupied from seat_snapshots"
                    )
                }
            # the last snapshot with data and the last overall both survive
            self.assertIn(final_with_data, kept)
            self.assertEqual(kept[final_with_data], 9)
            self.assertIn(failed_after, kept)
            self.assertTrue(upcoming_ids.issubset(kept))
            self.assertEqual(len(kept), 4)

            # running again removes nothing further
            self.assertEqual(repository.prune_snapshots(), 0)


class SupabaseRepositoryTests(unittest.TestCase):
    def _repository_with_request_log(self) -> tuple[SupabaseRepository, list[tuple]]:
        repository = SupabaseRepository("https://example.supabase.co", "service-key")
        requests: list[tuple] = []

        def fake_request(method, resource, query=None, payload=None, prefer=None):
            requests.append((method, resource, query, payload))
            if method == "GET":
                return [{"id": f"looked-up-{resource}"}]
            return [{"id": f"{resource}-1"}]

        patcher = patch.object(repository, "_request", side_effect=fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)
        return repository, requests

    def test_repeated_identical_movie_upserts_hit_network_once(self) -> None:
        repository, requests = self._repository_with_request_log()
        movie = Movie(normalized_title="the-quiet-frame", source_title="The Quiet Frame")

        first = repository.upsert_movie(movie)
        second = repository.upsert_movie(movie)

        self.assertEqual(first, second)
        self.assertEqual(len(requests), 1)

    def test_changed_movie_payload_upserts_again(self) -> None:
        repository, requests = self._repository_with_request_log()

        repository.upsert_movie(
            Movie(normalized_title="the-quiet-frame", source_title="The Quiet Frame")
        )
        repository.upsert_movie(
            Movie(
                normalized_title="the-quiet-frame",
                source_title="The Quiet Frame",
                rating="PG",
            )
        )

        self.assertEqual(len(requests), 2)

    def test_upsert_showing_and_snapshot_reuse_cached_ids(self) -> None:
        repository, requests = self._repository_with_request_log()
        repository.upsert_theater(
            Theater(
                chain="Landmark",
                name="Landmark Cinemas 8 Regina",
                city="Regina",
                external_id="landmark-regina",
                ticketing_url="https://as.landmarkcinemas.com/showtimes/regina",
            )
        )
        repository.upsert_movie(
            Movie(normalized_title="the-quiet-frame", source_title="The Quiet Frame")
        )
        repository.upsert_showing(
            Showing(
                theater_external_id="landmark-regina",
                movie_normalized_title="the-quiet-frame",
                starts_at=datetime(2026, 7, 23, 1, 15, tzinfo=timezone.utc),
                ticket_url="https://as.landmarkcinemas.com/showtimes/regina",
                source_id="landmark-regina-quiet-frame",
            )
        )
        repository.insert_snapshot(
            SeatSnapshot(
                showing_source_id="landmark-regina-quiet-frame",
                checked_at=datetime(2026, 7, 22, 23, 45, tzinfo=timezone.utc),
                inferred_occupied=2,
                available_seats=80,
                total_sellable_seats=82,
                raw_status="available",
                confidence="high",
            )
        )

        # theater + movie + showing + snapshot, and no lookup GETs in between
        self.assertEqual(len(requests), 4)
        self.assertEqual([method for method, *_ in requests], ["POST"] * 4)
        snapshot_payload = requests[3][3]
        self.assertEqual(snapshot_payload["showing_id"], "showings-1")

    def test_uncached_showing_falls_back_to_lookup(self) -> None:
        repository, requests = self._repository_with_request_log()

        repository.insert_snapshot(
            SeatSnapshot(
                showing_source_id="landmark-regina-unknown",
                checked_at=datetime(2026, 7, 22, 23, 45, tzinfo=timezone.utc),
                inferred_occupied=None,
                available_seats=None,
                total_sellable_seats=None,
                raw_status="failed",
                confidence="low",
            )
        )

        self.assertEqual([method for method, *_ in requests], ["GET", "POST"])
        self.assertEqual(requests[1][3]["showing_id"], "looked-up-showings")


if __name__ == "__main__":
    unittest.main()
