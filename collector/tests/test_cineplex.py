from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from collector.solocinema_collector import cineplex as cineplex_module
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
        self.assertEqual(
            showing.ticket_url,
            "https://www.cineplex.com/ticketing/preview?theatreId=4108&showtimeId=264346",
        )
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

    def test_write_cineplex_showings_defers_probe_beyond_window(self) -> None:
        def make_showing(name: str, starts_at: datetime) -> CineplexShowing:
            return CineplexShowing(
                movie_title=name,
                starts_at=starts_at,
                ticket_url=f"https://www.cineplex.com/ticketing/4108/{name}",
                source_id=f"cineplex-southland-cineplex-{name}",
                vista_session_id=name,
                location_id="4108",
                theater_external_id="cineplex-southland",
                is_online_ticketing_enabled=True,
                is_reserved_seating=True,
            )

        # July 5 and July 8, Regina time (UTC-6)
        near = make_showing("near", datetime(2026, 7, 6, 1, 15, tzinfo=UTC))
        far = make_showing("far", datetime(2026, 7, 9, 1, 15, tzinfo=UTC))
        probed: list[str] = []

        def fake_probe(showing: CineplexShowing, subscription_key=None):
            probed.append(showing.source_id)
            from collector.solocinema_collector.cineplex import _unknown_result

            return _unknown_result("probed")

        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'solocinema.sqlite'}"
            repository = SQLiteRepository(database_url)
            repository.init_schema()
            with patch(
                "collector.solocinema_collector.cineplex.probe_cineplex_seat_map",
                side_effect=fake_probe,
            ):
                summary = write_cineplex_showings(
                    repository,
                    [near, far],
                    database_url=database_url,
                    probe_seats=True,
                    probe_until=date(2026, 7, 6),
                )

            with repository.connect() as connection:
                snapshot_count = connection.execute(
                    "select count(*) as n from seat_snapshots"
                ).fetchone()["n"]
                showing_count = connection.execute(
                    "select count(*) as n from showings"
                ).fetchone()["n"]

        self.assertEqual(summary.status, "success")
        self.assertEqual(summary.checked, 2)
        self.assertEqual(probed, ["cineplex-southland-cineplex-near"])
        # both showings are written, but only the probed one gets a snapshot
        self.assertEqual(showing_count, 2)
        self.assertEqual(snapshot_count, 1)

    def test_write_cineplex_showings_skips_probe_for_started_showings(self) -> None:
        started = CineplexShowing(
            movie_title="Started Show",
            starts_at=datetime(2026, 7, 6, 1, 15, tzinfo=UTC),
            ticket_url="https://www.cineplex.com/ticketing/4108/started",
            source_id="cineplex-southland-cineplex-started",
            vista_session_id="started",
            location_id="4108",
            theater_external_id="cineplex-southland",
            is_online_ticketing_enabled=True,
            is_reserved_seating=True,
        )
        probed: list[str] = []

        def fake_probe(showing: CineplexShowing, subscription_key=None):
            probed.append(showing.source_id)
            from collector.solocinema_collector.cineplex import _unknown_result

            return _unknown_result("probed")

        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'solocinema.sqlite'}"
            repository = SQLiteRepository(database_url)
            repository.init_schema()
            with patch(
                "collector.solocinema_collector.cineplex.probe_cineplex_seat_map",
                side_effect=fake_probe,
            ):
                summary = write_cineplex_showings(
                    repository,
                    [started],
                    database_url=database_url,
                    probe_seats=True,
                    probe_until=date(2026, 7, 6),
                    # showing began more than three hours before this cutoff
                    probe_after=datetime(2026, 7, 6, 4, 30, tzinfo=UTC),
                )

        self.assertEqual(summary.status, "success")
        self.assertEqual(probed, [])


class CineplexRequestRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        cineplex_module.reset_retry_budget()
        self.addCleanup(cineplex_module.reset_retry_budget)
        self.slept: list[float] = []
        sleep_patch = patch.object(
            cineplex_module.time, "sleep", side_effect=self.slept.append
        )
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    @staticmethod
    def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
        headers = {"Retry-After": retry_after} if retry_after else {}
        return HTTPError("https://apis.cineplex.com/prod/x", code, "err", headers, None)

    @staticmethod
    def _ok_response(payload: object):
        response = MagicMock()
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda self, *args: False
        return response

    def test_retries_transient_403_then_succeeds(self) -> None:
        with patch.object(
            cineplex_module,
            "urlopen",
            side_effect=[self._http_error(403), self._ok_response({"ok": True})],
        ) as urlopen:
            payload = cineplex_module._open_json(
                "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes?locationId=4108",
                subscription_key="key",
            )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(self.slept, [2.0])

    def test_honours_retry_after_header(self) -> None:
        with patch.object(
            cineplex_module,
            "urlopen",
            side_effect=[
                self._http_error(429, retry_after="9"),
                self._ok_response({"ok": True}),
            ],
        ):
            cineplex_module._open_json(
                "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes?locationId=4108",
                subscription_key="key",
            )

        self.assertEqual(self.slept, [9.0])

    def test_does_not_retry_a_rejected_key(self) -> None:
        with patch.object(
            cineplex_module, "urlopen", side_effect=self._http_error(401)
        ) as urlopen:
            with self.assertRaises(HTTPError):
                cineplex_module._open_json(
                    "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes?locationId=4108",
                    subscription_key="stale",
                )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(self.slept, [])

    def test_raises_after_retries_are_exhausted(self) -> None:
        with patch.object(
            cineplex_module, "urlopen", side_effect=self._http_error(503)
        ) as urlopen:
            with self.assertRaises(HTTPError):
                cineplex_module._open_json(
                    "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes?locationId=4108",
                    subscription_key="key",
                )

        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(self.slept, [2.0, 6.0])

    def test_retry_budget_stops_sleeping_during_a_sustained_outage(self) -> None:
        with patch.object(
            cineplex_module, "urlopen", side_effect=self._http_error(403)
        ):
            for _ in range(100):
                with self.assertRaises(HTTPError):
                    cineplex_module._open_json(
                        "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes?locationId=4108",
                        subscription_key="key",
                    )

        self.assertLessEqual(
            sum(self.slept), cineplex_module.CINEPLEX_RETRY_BUDGET_SECONDS
        )


if __name__ == "__main__":
    unittest.main()
