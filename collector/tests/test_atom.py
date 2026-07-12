from __future__ import annotations

import io
import unittest
from datetime import UTC, datetime
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from collector.solocinema_collector import atom
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


def _http_429(retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://www.atomtickets.com/x", 429, "Too Many Requests", headers, io.BytesIO())


class _FakeResponse:
    headers = Message()

    @staticmethod
    def read() -> bytes:
        return b"ok"


class _FlakyOpener:
    def __init__(self, failures: list[HTTPError]) -> None:
        self.failures = failures
        self.attempts = 0

    def open(self, request, timeout=None):
        self.attempts += 1
        if self.failures:
            raise self.failures.pop(0)
        return _FakeResponse()


class AtomOpenTextRetryTests(unittest.TestCase):
    def test_retries_on_429_and_recovers(self) -> None:
        opener = _FlakyOpener([_http_429(), _http_429()])
        with patch.object(atom.time, "sleep") as sleep:
            text = atom._open_text("https://www.atomtickets.com/checkout/1", opener=opener)
        self.assertEqual(text, "ok")
        self.assertEqual(opener.attempts, 3)
        retry_sleeps = [
            call.args[0]
            for call in sleep.call_args_list
            if call.args[0] > atom.ATOM_REQUEST_INTERVAL_SECONDS
        ]
        self.assertEqual(retry_sleeps, list(atom.ATOM_RETRY_DELAYS_SECONDS))

    def test_raises_when_429_persists_past_retries(self) -> None:
        opener = _FlakyOpener([_http_429()] * (len(atom.ATOM_RETRY_DELAYS_SECONDS) + 1))
        with patch.object(atom.time, "sleep"):
            with self.assertRaises(HTTPError):
                atom._open_text("https://www.atomtickets.com/checkout/1", opener=opener)
        self.assertEqual(opener.attempts, len(atom.ATOM_RETRY_DELAYS_SECONDS) + 1)

    def test_does_not_retry_other_http_errors(self) -> None:
        error = HTTPError("https://www.atomtickets.com/x", 404, "Not Found", Message(), io.BytesIO())
        opener = _FlakyOpener([error])
        with patch.object(atom.time, "sleep"):
            with self.assertRaises(HTTPError):
                atom._open_text("https://www.atomtickets.com/checkout/1", opener=opener)
        self.assertEqual(opener.attempts, 1)

    def test_honors_retry_after_header_with_cap(self) -> None:
        self.assertEqual(atom._retry_after_seconds(_http_429("7")), 7.0)
        self.assertEqual(
            atom._retry_after_seconds(_http_429("999")), atom.ATOM_RETRY_AFTER_CAP_SECONDS
        )
        self.assertIsNone(atom._retry_after_seconds(_http_429()))
        self.assertIsNone(atom._retry_after_seconds(_http_429("Wed, 21 Oct 2026 07:28:00 GMT")))

    def test_throttle_spaces_requests(self) -> None:
        atom._last_request_at = None
        opener = _FlakyOpener([])
        with patch.object(atom.time, "sleep") as sleep, patch.object(
            atom.time, "monotonic", side_effect=[100.0, 100.1, 100.1]
        ):
            atom._open_text("https://www.atomtickets.com/checkout/1", opener=opener)
            atom._open_text("https://www.atomtickets.com/checkout/2", opener=opener)
        waits = [call.args[0] for call in sleep.call_args_list]
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], atom.ATOM_REQUEST_INTERVAL_SECONDS - 0.1)
        atom._last_request_at = None


if __name__ == "__main__":
    unittest.main()
