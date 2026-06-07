from __future__ import annotations

import unittest
from datetime import UTC, datetime

from collector.solocinema_collector.atom import AtomTheaterParser


class AtomCollectorTests(unittest.TestCase):
    def test_extracts_atom_showings_from_theater_html(self) -> None:
        html = """
        <a href="#" data-value="{&quot;serverFormat&quot;:&quot;2026-06-06&quot;,&quot;isSelected&quot;:true}">Today</a>
        <li data-showtime-entity-group>
          <h2 data-qa="ProductionHeader_Title"><a>Backrooms</a></h2>
          <div class="format-showtimes" data-showtime-tags="[&quot;Standard&quot;,&quot;Reserved Seating&quot;,&quot;Recliner&quot;]">
            <a class="btn btn-showtime btn-block" href="/checkout/630921736">7:35 PM</a>
          </div>
        </li>
        """

        parser = AtomTheaterParser("https://www.atomtickets.com/theaters/landmark-cinemas-regina/49885")
        parser.feed(html)

        self.assertEqual(len(parser.showings), 1)
        showing = parser.showings[0]
        self.assertEqual(showing.movie_title, "Backrooms")
        self.assertEqual(showing.starts_at, datetime(2026, 6, 7, 1, 35, tzinfo=UTC))
        self.assertEqual(showing.ticket_url, "https://www.atomtickets.com/checkout/630921736")
        self.assertEqual(showing.source_id, "landmark-regina-atom-630921736")
        self.assertEqual(showing.format, "Standard")

    def test_extracts_unticketed_atom_buttons_when_enabled(self) -> None:
        html = """
        <a href="#" data-value="{&quot;serverFormat&quot;:&quot;2026-06-06&quot;,&quot;isSelected&quot;:true}">Today</a>
        <li data-showtime-entity-group>
          <h2 data-qa="ProductionHeader_Title"><a>Scary Movie</a></h2>
          <div class="format-showtimes" data-showtime-tags="[&quot;Standard&quot;]">
            <button class="btn btn-showtime btn-block" disabled data-qa="Showtimes_Button">1:50 PM</button>
          </div>
        </li>
        """

        parser = AtomTheaterParser(
            "https://www.atomtickets.com/theaters/cineplex-odeon-southland-mall-cinemas/6446",
            source_prefix="cineplex-southland",
            include_unticketed=True,
        )
        parser.feed(html)

        self.assertEqual(len(parser.showings), 1)
        showing = parser.showings[0]
        self.assertEqual(showing.movie_title, "Scary Movie")
        self.assertEqual(showing.starts_at, datetime(2026, 6, 6, 19, 50, tzinfo=UTC))
        self.assertEqual(
            showing.ticket_url,
            "https://www.atomtickets.com/theaters/cineplex-odeon-southland-mall-cinemas/6446",
        )
        self.assertIsNone(showing.seat_map_url)
        self.assertTrue(showing.source_id.startswith("cineplex-southland-atom-scary-movie-"))
        self.assertEqual(showing.format, "Standard")

    def test_ignores_unticketed_atom_buttons_by_default(self) -> None:
        html = """
        <a href="#" data-value="{&quot;serverFormat&quot;:&quot;2026-06-06&quot;,&quot;isSelected&quot;:true}">Today</a>
        <li data-showtime-entity-group>
          <h2 data-qa="ProductionHeader_Title"><a>Scary Movie</a></h2>
          <div class="format-showtimes" data-showtime-tags="[&quot;Standard&quot;]">
            <button class="btn btn-showtime btn-block" disabled data-qa="Showtimes_Button">1:50 PM</button>
          </div>
        </li>
        """

        parser = AtomTheaterParser(
            "https://www.atomtickets.com/theaters/cineplex-odeon-southland-mall-cinemas/6446"
        )
        parser.feed(html)

        self.assertEqual(parser.showings, [])


if __name__ == "__main__":
    unittest.main()
