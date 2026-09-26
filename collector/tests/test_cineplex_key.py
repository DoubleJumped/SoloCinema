from __future__ import annotations

import unittest

from collector.solocinema_collector.cineplex_key import (
    CINEPLEX_HOME_URL,
    extract_subscription_keys,
    fetch_site_key,
    refreshed_key,
)

OLD = "a" * 32
NEW = "b" * 32
BANNER = "c" * 32
CHUNK = "https://www.cineplex.com/next-static-files/_next/static/chunks/app-1.js"


def _site(chunks: dict[str, str]):
    home = "".join(f'<script src="{url}"></script>' for url in chunks)
    pages = {CINEPLEX_HOME_URL: home, **chunks}

    def fetch(url: str) -> str:
        if url not in pages:
            raise OSError(f"404 {url}")
        return pages[url]

    return fetch


class CineplexKeyTests(unittest.TestCase):
    def test_extracts_both_key_spellings(self) -> None:
        text = f'ocpApimSubscriptionKey:"{NEW}", {{"Ocp-Apim-Subscription-Key":"{NEW}"}}'
        self.assertEqual(extract_subscription_keys(text)[NEW], 2)

    def test_most_common_key_in_the_bundles_wins(self) -> None:
        bundle = (
            f'"Ocp-Apim-Subscription-Key":"{NEW}"' * 3
            + f'"Ocp-Apim-Subscription-Key":"{BANNER}"'
        )
        self.assertEqual(fetch_site_key(_site({CHUNK: bundle})), NEW)

    def test_a_missing_chunk_does_not_sink_the_scan(self) -> None:
        other = CHUNK.replace("app-1", "app-2")
        pages = {CHUNK: f'"Ocp-Apim-Subscription-Key":"{NEW}"'}
        home = f'<script src="{other}"></script><script src="{CHUNK}"></script>'

        def fetch(url: str) -> str:
            if url == CINEPLEX_HOME_URL:
                return home
            if url not in pages:
                raise OSError("404")
            return pages[url]

        self.assertEqual(fetch_site_key(fetch), NEW)

    def test_adopts_a_validated_rotated_key(self) -> None:
        fetch = _site({CHUNK: f'"Ocp-Apim-Subscription-Key":"{NEW}"'})
        self.assertEqual(refreshed_key(OLD, fetch=fetch, validate=lambda key: True), NEW)

    def test_rejects_a_site_key_that_fails_validation(self) -> None:
        fetch = _site({CHUNK: f'"Ocp-Apim-Subscription-Key":"{NEW}"'})
        self.assertIsNone(refreshed_key(OLD, fetch=fetch, validate=lambda key: False))

    def test_same_key_on_the_site_means_outage_not_rotation(self) -> None:
        fetch = _site({CHUNK: f'"Ocp-Apim-Subscription-Key":"{OLD}"'})
        calls = []
        self.assertIsNone(refreshed_key(OLD, fetch=fetch, validate=calls.append))
        self.assertEqual(calls, [])

    def test_unreachable_site_yields_none(self) -> None:
        def fetch(url: str) -> str:
            raise OSError("down")

        self.assertIsNone(refreshed_key(OLD, fetch=fetch, validate=lambda key: True))


if __name__ == "__main__":
    unittest.main()
