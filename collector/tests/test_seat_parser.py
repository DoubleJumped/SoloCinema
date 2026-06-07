from __future__ import annotations

import json
import unittest
from pathlib import Path

from collector.solocinema_collector.seat_parser import (
    parse_atom_seat_map_fragments,
    parse_dom_seats,
    parse_structured_seats,
)


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"


class SeatParserTests(unittest.TestCase):
    def test_structured_payload_counts_occupied_and_blocked(self) -> None:
        payload = json.loads((FIXTURE_DIR / "landmark_seatmap.json").read_text())
        result = parse_structured_seats(payload)

        self.assertEqual(result.raw_status, "available")
        self.assertEqual(result.inferred_occupied, 3)
        self.assertEqual(result.available_seats, 5)
        self.assertEqual(result.total_sellable_seats, 8)
        self.assertEqual(result.blocked_seats, 1)
        self.assertEqual(result.confidence, "medium")

    def test_dom_payload_counts_unknown_accessibility_as_lower_confidence(self) -> None:
        html = (FIXTURE_DIR / "seatmap_dom.html").read_text()
        result = parse_dom_seats(html)

        self.assertEqual(result.inferred_occupied, 3)
        self.assertEqual(result.available_seats, 2)
        self.assertEqual(result.unknown_seats, 1)
        self.assertEqual(result.confidence, "low")

    def test_missing_seats_returns_unknown(self) -> None:
        result = parse_structured_seats({"message": "no seat map"})

        self.assertIsNone(result.inferred_occupied)
        self.assertEqual(result.raw_status, "unknown")
        self.assertEqual(result.confidence, "low")

    def test_atom_fragments_merge_area_categories_by_seat(self) -> None:
        standard = """
        <svg>
          <g id="seat-a1" class="seat" seat-name="A1" is-available="true" seat-type="LoveSeatLeft"></g>
          <g id="seat-a2" class="seat" seat-name="A2" is-available="false" seat-type="Unavailable"></g>
          <g id="seat-a3" class="seat" seat-name="A3" is-available="false" seat-type="Unavailable"></g>
        </svg>
        """
        premiere = """
        <svg>
          <g id="seat-a1" class="seat" seat-name="A1" is-available="false" seat-type="Unavailable"></g>
          <g id="seat-a2" class="seat" seat-name="A2" is-available="true" seat-type="LoveSeatRight"></g>
          <g id="seat-a3" class="seat" seat-name="A3" is-available="false" seat-type="Unavailable"></g>
        </svg>
        """

        result = parse_atom_seat_map_fragments([standard, premiere])

        self.assertEqual(result.available_seats, 2)
        self.assertEqual(result.inferred_occupied, 1)
        self.assertEqual(result.total_sellable_seats, 3)
        self.assertEqual(result.confidence, "high")


if __name__ == "__main__":
    unittest.main()
