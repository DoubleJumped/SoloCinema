from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from collector.solocinema_collector.landmark import (
    LandmarkShowing,
    _is_access_denied,
    extract_showings_from_dom_candidates,
    extract_showings_from_payloads,
    normalize_movie_title,
    write_landmark_showings,
)
from collector.solocinema_collector.storage import SQLiteRepository


class LandmarkCollectorTests(unittest.TestCase):
    def test_extracts_showings_from_nested_payload(self) -> None:
        payload = {
            "movies": [
                {
                    "movieTitle": "The Quiet Frame",
                    "showtimes": [
                        {
                            "sessionId": "abc123",
                            "showDateTime": "2026-06-06T19:15:00",
                            "ticketUrl": "/tickets/abc123",
                            "seatMapUrl": "/seat-map/abc123",
                            "experienceName": "Laser Ultra",
                            "auditorium": "1",
                        }
                    ],
                }
            ]
        }

        showings = extract_showings_from_payloads(
            [payload],
            "https://as.landmarkcinemas.com/showtimes/regina",
            now=datetime(2026, 6, 6, tzinfo=UTC),
        )

        self.assertEqual(len(showings), 1)
        self.assertEqual(showings[0].movie_title, "The Quiet Frame")
        self.assertEqual(showings[0].source_id, "landmark-regina-abc123")
        self.assertEqual(showings[0].ticket_url, "https://as.landmarkcinemas.com/tickets/abc123")
        self.assertEqual(showings[0].seat_map_url, "https://as.landmarkcinemas.com/seat-map/abc123")
        self.assertEqual(showings[0].format, "Laser Ultra")
        self.assertEqual(showings[0].auditorium, "1")

    def test_extracts_showing_when_parent_has_date_and_child_has_time(self) -> None:
        payload = {
            "movieTitle": "Late Bloomers",
            "showDate": "2026-06-06",
            "sessions": [
                {
                    "sessionId": "late-715",
                    "showTime": "7:15 PM",
                    "ticketUrl": "/tickets/late-715",
                }
            ],
        }

        showings = extract_showings_from_payloads(
            [payload],
            "https://as.landmarkcinemas.com/showtimes/regina",
            now=datetime(2026, 6, 6, tzinfo=UTC),
        )

        self.assertEqual(len(showings), 1)
        self.assertEqual(showings[0].movie_title, "Late Bloomers")
        self.assertEqual(showings[0].starts_at, datetime(2026, 6, 7, 1, 15, tzinfo=UTC))

    def test_extracts_showing_from_dom_candidate(self) -> None:
        candidates = [
            {
                "href": "https://as.landmarkcinemas.com/tickets/quiet-frame",
                "text": "Tickets",
                "nearbyText": "The Quiet Frame\nSaturday, June 6, 2026\n7:15 PM\nLaser Ultra",
                "attrs": {"data-seat-map-url": "/seat-map/quiet-frame"},
            }
        ]

        showings = extract_showings_from_dom_candidates(
            candidates,
            "https://as.landmarkcinemas.com/showtimes/regina",
            now=datetime(2026, 6, 6, tzinfo=UTC),
        )

        self.assertEqual(len(showings), 1)
        self.assertEqual(showings[0].movie_title, "The Quiet Frame")
        self.assertEqual(showings[0].format, "Laser Ultra")
        self.assertEqual(showings[0].seat_map_url, "https://as.landmarkcinemas.com/seat-map/quiet-frame")

    def test_write_landmark_showings_without_seat_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'solocinema.sqlite'}"
            repository = SQLiteRepository(database_url)
            repository.init_schema()

            summary = write_landmark_showings(
                repository,
                [
                    LandmarkShowing(
                        movie_title="The Quiet Frame",
                        starts_at=datetime(2026, 6, 7, 1, 15, tzinfo=UTC),
                        ticket_url="https://as.landmarkcinemas.com/tickets/abc123",
                        source_id="landmark-regina-abc123",
                        format="Laser Ultra",
                    )
                ],
                database_url=database_url,
                probe_seats=False,
            )
            rows = repository.list_screenings()

            self.assertEqual(summary.status, "success")
            self.assertEqual(summary.checked, 1)
            self.assertEqual(rows[0]["movie_title"], "The Quiet Frame")
            self.assertEqual(rows[0]["raw_status"], "unknown")

    def test_normalizes_movie_title_to_stable_slug(self) -> None:
        self.assertEqual(normalize_movie_title("Amelie: The Musical!"), "amelie-the-musical")

    def test_detects_landmark_edge_access_denied(self) -> None:
        self.assertTrue(
            _is_access_denied(
                "Access Denied",
                "You don't have permission to access this server. https://errors.edgesuite.net/ref",
            )
        )


if __name__ == "__main__":
    unittest.main()
