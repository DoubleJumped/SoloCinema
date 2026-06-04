from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collector.solocinema_collector.models import Movie, SeatSnapshot, Showing, Theater
from collector.solocinema_collector.storage import SQLiteRepository


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


if __name__ == "__main__":
    unittest.main()
