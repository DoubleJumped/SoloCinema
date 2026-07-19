from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from collector.solocinema_collector.imax import (
    ImaxItem,
    ImaxShowing,
    KRAMER_AUDITORIUM_CAPACITY,
    parse_imax_calendar,
    parse_imax_items,
    parse_imax_seat_svg,
    result_from_remaining,
    write_imax_showings,
    _API_KEY,
)
from collector.solocinema_collector.storage import SQLiteRepository
from collector.solocinema_collector.url_guard import require_allowed_url


FIXTURES = Path(__file__).parents[1] / "fixtures"


class ImaxParsingTests(unittest.TestCase):
    def test_parses_items_from_listing_page(self) -> None:
        html = (FIXTURES / "imax_listing.html").read_text(encoding="utf-8")

        items = parse_imax_items(html)

        self.assertEqual(
            items,
            [
                ImaxItem(item_id="3701", title="Call of the Dolphins 2D"),
                ImaxItem(item_id="3702", title="Call of the Dolphins 3D"),
                ImaxItem(item_id="3608", title="The Odyssey: The IMAX 70mm Experience"),
            ],
        )

    def test_ignores_cart_heading(self) -> None:
        html = '<h2>Your Order</h2><a href="/DateSelection.aspx?item=9">x</a>'
        self.assertEqual(parse_imax_items(html), [])

    def test_parses_calendar_showtimes_with_remaining_counts(self) -> None:
        html = (FIXTURES / "imax_calendar_all.html").read_text(encoding="utf-8")
        item = ImaxItem(item_id="3608", title="The Odyssey: The IMAX 70mm Experience")

        showings = parse_imax_calendar(html, item)

        self.assertEqual(len(showings), 3)
        sold_out = showings[0]
        self.assertEqual(sold_out.schedule_id, "203853")
        self.assertEqual(sold_out.remaining, 0)
        self.assertEqual(sold_out.source_id, "kramer-imax-atms-203853")
        self.assertEqual(
            sold_out.ticket_url,
            "https://tickets.sasksciencecentre.com/Selection.aspx?sch=203853",
        )
        # 3:00 PM Regina (UTC-6, no DST) == 21:00 UTC
        self.assertEqual(sold_out.starts_at, datetime(2026, 7, 19, 21, 0, tzinfo=UTC))

        matinee = showings[1]
        self.assertEqual(matinee.remaining, 145)
        self.assertEqual(matinee.starts_at, datetime(2026, 7, 20, 17, 45, tzinfo=UTC))

        # Third listing has no "N Remaining" text.
        self.assertIsNone(showings[2].remaining)

    def test_counts_locked_seats_in_svg(self) -> None:
        svg = (FIXTURES / "imax_seatmap.svg").read_text(encoding="utf-8")

        result = parse_imax_seat_svg(svg)

        # 5 seats, 3 carry the bare `locked` attribute. The word "locked"
        # inside a message="..." popover must not count.
        self.assertEqual(result.total_sellable_seats, 5)
        self.assertEqual(result.inferred_occupied, 3)
        self.assertEqual(result.available_seats, 2)
        self.assertEqual(result.raw_status, "available")
        self.assertEqual(result.confidence, "medium")

    def test_empty_svg_reports_unknown(self) -> None:
        result = parse_imax_seat_svg("<svg></svg>")
        self.assertEqual(result.raw_status, "unknown")
        self.assertIsNone(result.inferred_occupied)

    def test_remaining_fallback_infers_against_capacity(self) -> None:
        result = result_from_remaining(145)
        self.assertEqual(result.inferred_occupied, KRAMER_AUDITORIUM_CAPACITY - 145)
        self.assertEqual(result.available_seats, 145)
        self.assertEqual(result.total_sellable_seats, KRAMER_AUDITORIUM_CAPACITY)
        self.assertEqual(result.confidence, "low")

    def test_remaining_fallback_without_count_is_unknown(self) -> None:
        result = result_from_remaining(None)
        self.assertEqual(result.raw_status, "unknown")
        self.assertIsNone(result.inferred_occupied)

    def test_api_key_scrape_pattern(self) -> None:
        html = 'let options = { id: 203852, apiKey: "key-ssc-8001482daac3efd0464d67b3", containerId: "chart" }'
        match = _API_KEY.search(html)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "key-ssc-8001482daac3efd0464d67b3")

    def test_url_guard_allows_imax_hosts(self) -> None:
        require_allowed_url("https://tickets.sasksciencecentre.com/default.aspx?tagid=18")
        require_allowed_url(
            "https://seats-api.ticketclick.com/api/seatingcharts/svg/organization/k/atmsSchedule/1"
        )
        with self.assertRaises(ValueError):
            require_allowed_url("https://evil.example.com/")


class ImaxWriteTests(unittest.TestCase):
    def test_writes_showings_with_calendar_snapshots(self) -> None:
        showing = ImaxShowing(
            movie_title="The Odyssey: The IMAX 70mm Experience",
            starts_at=datetime(2026, 7, 20, 17, 45, tzinfo=UTC),
            ticket_url="https://tickets.sasksciencecentre.com/Selection.aspx?sch=204086",
            source_id="kramer-imax-atms-204086",
            schedule_id="204086",
            item_id="3608",
            remaining=145,
        )
        with tempfile.TemporaryDirectory() as tmp:
            database_url = f"sqlite:///{tmp}/imax.sqlite"
            repository = SQLiteRepository(database_url)
            repository.init_schema()

            summary = write_imax_showings(
                repository,
                [showing],
                database_url=database_url,
                probe_seats=False,
            )

            self.assertEqual(summary.status, "success")
            self.assertEqual(summary.checked, 1)
            self.assertEqual(summary.failed, 0)
            rows = [dict(row) for row in repository.list_screenings()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["theater_name"], "Kramer IMAX Theatre")
            self.assertEqual(rows[0]["raw_status"], "available")
            self.assertEqual(
                rows[0]["inferred_occupied"], KRAMER_AUDITORIUM_CAPACITY - 145
            )


if __name__ == "__main__":
    unittest.main()
