from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from collector.solocinema_collector.cineplex import (
    CineplexShowing,
    extract_cineplex_showings,
    parse_cineplex_seat_responses,
    write_cineplex_showings,
)
from collector.solocinema_collector.storage import SQLiteRepository


class CineplexCollectorTests(unittest.TestCase):
    def test_extracts_cineplex_showings_from_nested_payload(self) -> None:
        payload = {
            "movies": [
                {
                    "title": "The Quiet Frame",
                    "showDate": "2026-06-06",
                    "showtimes": [
                        {
                            "vistaSessionId": "263673",
                            "showTime": "7:15 PM",
                            "formatName": "UltraAVX",
                            "screenName": "5",
                            "isOnlineTicketingEnabled": True,
                            "isReservedSeating": True,
                        }
                    ],
                }
            ]
        }

        showings = extract_cineplex_showings(
            payload,
            location_id="4108",
            theater_external_id="cineplex-southland",
            now=datetime(2026, 6, 6, tzinfo=UTC),
        )

        self.assertEqual(len(showings), 1)
        showing = showings[0]
        self.assertEqual(showing.movie_title, "The Quiet Frame")
        self.assertEqual(showing.starts_at, datetime(2026, 6, 7, 1, 15, tzinfo=UTC))
        self.assertEqual(showing.source_id, "cineplex-southland-cineplex-263673")
        self.assertEqual(showing.vista_session_id, "263673")
        self.assertEqual(showing.format, "UltraAVX")
        self.assertEqual(showing.auditorium, "5")
        self.assertTrue(showing.is_online_ticketing_enabled)
        self.assertTrue(showing.is_reserved_seating)

    def test_extracts_cineplex_showings_from_live_api_shape(self) -> None:
        payload = [
            {
                "theatre": "Cineplex Cinemas Southland",
                "theatreId": 4108,
                "dates": [
                    {
                        "startDate": "2026-06-08T00:00:00",
                        "movies": [
                            {
                                "name": "Scary Movie",
                                "experiences": [
                                    {
                                        "experienceTypes": ["Recliner"],
                                        "sessions": [
                                            {
                                                "ticketingUrl": "https://apis.cineplex.com/prod/ticketing/api/v1/routing/redirect-to-ticketing?VistaSessionId=264346&LocationId=4108",
                                                "vistaSessionId": 264346,
                                                "showStartDateTime": "2026-06-08T13:50:00",
                                                "showStartDateTimeUtc": "2026-06-08T19:50:00Z",
                                                "isReservedSeating": True,
                                                "isShowtimeEnabledOnline": True,
                                                "auditorium": "Aud 2",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

        showings = extract_cineplex_showings(
            payload,
            location_id="4108",
            theater_external_id="cineplex-southland",
            now=datetime(2026, 6, 8, tzinfo=UTC),
        )

        self.assertEqual(len(showings), 1)
        showing = showings[0]
        self.assertEqual(showing.movie_title, "Scary Movie")
        self.assertEqual(showing.starts_at, datetime(2026, 6, 8, 19, 50, tzinfo=UTC))
        self.assertEqual(showing.source_id, "cineplex-southland-cineplex-264346")
        self.assertEqual(showing.vista_session_id, "264346")
        self.assertEqual(showing.format, "Recliner")
        self.assertEqual(showing.auditorium, "Aud 2")
        self.assertTrue(showing.ticket_url.startswith("https://apis.cineplex.com/prod/ticketing"))
        self.assertTrue(showing.is_online_ticketing_enabled)
        self.assertTrue(showing.is_reserved_seating)

    def test_counts_cineplex_layout_and_availability(self) -> None:
        layout = {
            "seatLayout": {
                "areas": [
                    {
                        "rows": [
                            {
                                "seats": [
                                    {"seatId": "a1", "position": {"areaNumber": 1, "rowNumber": 1, "columnNumber": 1}},
                                    {"seatId": "a2", "position": {"areaNumber": 1, "rowNumber": 1, "columnNumber": 2}},
                                    {"seatId": "a3", "position": {"areaNumber": 1, "rowNumber": 1, "columnNumber": 3}},
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        availability = {
            "showtimeSeats": [
                {
                    "seats": [
                        {"seatId": "a1", "status": "Available"},
                        {"seatId": "a2", "status": "Occupied"},
                        {"seatId": "a3", "status": "Broken"},
                    ]
                }
            ]
        }

        result = parse_cineplex_seat_responses(layout, availability)

        self.assertEqual(result.raw_status, "available")
        self.assertEqual(result.available_seats, 1)
        self.assertEqual(result.inferred_occupied, 2)
        self.assertEqual(result.total_sellable_seats, 3)
        self.assertEqual(result.blocked_seats, 1)
        self.assertEqual(result.confidence, "medium")

    def test_counts_cineplex_live_availability_map_shape(self) -> None:
        layout = {
            "standardSeats": {
                "rows": [
                    {
                        "seats": [
                            {"id": "1_2_3", "label": "HW1", "type": "Wheelchair"},
                            {"id": "1_2_4", "label": "HC2", "type": "Companion"},
                            {"id": "1_2_5", "label": "H3", "type": "Standard"},
                        ]
                    }
                ]
            }
        }
        availability = {
            "seatAvailabilities": {
                "1_2_3": "Available",
                "1_2_4": "Occupied",
                "1_2_5": "Broken",
            },
            "isSoldOut": False,
        }

        result = parse_cineplex_seat_responses(layout, availability)

        self.assertEqual(result.available_seats, 1)
        self.assertEqual(result.inferred_occupied, 2)
        self.assertEqual(result.total_sellable_seats, 3)
        self.assertEqual(result.blocked_seats, 1)
        self.assertEqual(result.confidence, "medium")

    def test_write_cineplex_showings_without_seat_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'solocinema.sqlite'}"
            repository = SQLiteRepository(database_url)
            repository.init_schema()

            summary = write_cineplex_showings(
                repository,
                [
                    CineplexShowing(
                        movie_title="The Quiet Frame",
                        starts_at=datetime(2026, 6, 7, 1, 15, tzinfo=UTC),
                        ticket_url="https://www.cineplex.com/ticketing/4108/263673",
                        source_id="cineplex-southland-cineplex-263673",
                        vista_session_id="263673",
                        location_id="4108",
                        theater_external_id="cineplex-southland",
                        format="UltraAVX",
                        auditorium="5",
                    )
                ],
                database_url=database_url,
                probe_seats=False,
            )
            rows = repository.list_screenings()

            self.assertEqual(summary.status, "success")
            self.assertEqual(summary.checked, 1)
            self.assertEqual(rows[0]["movie_title"], "The Quiet Frame")
            self.assertEqual(rows[0]["theater_name"], "Cineplex Cinemas Southland")
            self.assertEqual(rows[0]["raw_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
