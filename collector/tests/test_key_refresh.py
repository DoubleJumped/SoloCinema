from __future__ import annotations

import unittest

from collector.solocinema_collector.key_refresh import (
    CINEPLEX_HOME_URL,
    extract_subscription_keys,
    fetch_site_key,
    refresh_cineplex_key,
)


OLD_KEY = "a" * 32
NEW_KEY = "dcdac5601d864addbc2675a2e96cb1f8"
BANNER_KEY = "477f072109904a55927ba2c3bf9f77e3"

HOME_HTML = (
    '<script src="https://www.cineplex.com/next-static-files/_next/static/chunks/'
    'pages/_app-667bfbdc68f92616.js"></script>'
    '<script src="https://www.cineplex.com/next-static-files/_next/static/chunks/'
    '9026-55dab940bc0d37c9.js"></script>'
    '<script src="https://evil.example.com/chunks/injected.js"></script>'
)
APP_CHUNK = (
    f'api",ocpApimSubscriptionKey:"{NEW_KEY}"}},posterApi:{{'
    f'ocpApimSubscriptionKey:"{NEW_KEY}"}},headers:{{'
    f'"Ocp-Apim-Subscription-Key":"{NEW_KEY}",CCToken:x}}'
)
MISC_CHUNK = f'{{headers:{{"Ocp-Apim-Subscription-Key":"{BANNER_KEY}"}}}}'


def fake_fetch(url: str) -> str:
    if url == CINEPLEX_HOME_URL:
        return HOME_HTML
    if "_app-" in url:
        return APP_CHUNK
    if "9026-" in url:
        return MISC_CHUNK
    raise AssertionError(f"Unexpected fetch: {url}")


class ExtractionTests(unittest.TestCase):
    def test_extracts_keys_from_config_and_header_forms(self) -> None:
        counts = extract_subscription_keys(APP_CHUNK)
        self.assertEqual(counts[NEW_KEY], 3)

    def test_ignores_non_key_hex(self) -> None:
        counts = extract_subscription_keys('sha:"deadbeef", other:"12345"')
        self.assertEqual(sum(counts.values()), 0)

    def test_fetch_site_key_picks_most_common_key(self) -> None:
        self.assertEqual(fetch_site_key(fetch=fake_fetch), NEW_KEY)

    def test_fetch_site_key_only_follows_cineplex_chunks(self) -> None:
        fetched: list[str] = []

        def recording_fetch(url: str) -> str:
            fetched.append(url)
            return fake_fetch(url)

        fetch_site_key(fetch=recording_fetch)
        self.assertTrue(all("cineplex.com" in url for url in fetched))

    def test_fetch_site_key_returns_none_when_no_keys(self) -> None:
        self.assertIsNone(fetch_site_key(fetch=lambda url: "<html></html>"))


class RefreshTests(unittest.TestCase):
    def refresh(self, current_key, valid_keys, dry_run=False, force=False, render_ok=True):
        self.render_calls: list[str] = []

        def update_render(key: str) -> bool:
            self.render_calls.append(key)
            return render_ok

        return refresh_cineplex_key(
            current_key,
            dry_run=dry_run,
            force=force,
            fetch=fake_fetch,
            validate=lambda key: key in valid_keys,
            update_render=update_render,
        )

    def test_valid_current_key_is_a_no_op(self) -> None:
        result = self.refresh(OLD_KEY, valid_keys={OLD_KEY})
        self.assertTrue(result.current_key_valid)
        self.assertFalse(result.rotated)
        self.assertEqual(result.active_key, OLD_KEY)
        self.assertEqual(self.render_calls, [])

    def test_dead_key_rotates_to_validated_site_key(self) -> None:
        result = self.refresh(OLD_KEY, valid_keys={NEW_KEY})
        self.assertFalse(result.current_key_valid)
        self.assertTrue(result.rotated)
        self.assertEqual(result.active_key, NEW_KEY)
        self.assertTrue(result.render_updated)
        self.assertEqual(self.render_calls, [NEW_KEY])

    def test_dry_run_never_updates_render(self) -> None:
        result = self.refresh(OLD_KEY, valid_keys={NEW_KEY}, dry_run=True)
        self.assertFalse(result.rotated)
        self.assertFalse(result.render_updated)
        self.assertEqual(result.active_key, NEW_KEY)
        self.assertEqual(self.render_calls, [])

    def test_invalid_site_key_is_not_adopted(self) -> None:
        result = self.refresh(OLD_KEY, valid_keys=set())
        self.assertFalse(result.rotated)
        self.assertIsNone(result.active_key)
        self.assertEqual(self.render_calls, [])

    def test_site_shipping_our_dead_key_is_reported_as_outage(self) -> None:
        result = self.refresh(NEW_KEY, valid_keys=set())
        self.assertFalse(result.rotated)
        self.assertIn("outage", result.message)
        self.assertEqual(self.render_calls, [])

    def test_force_with_unchanged_key_does_not_touch_render(self) -> None:
        result = self.refresh(NEW_KEY, valid_keys={NEW_KEY}, force=True)
        self.assertFalse(result.rotated)
        self.assertEqual(result.active_key, NEW_KEY)
        self.assertEqual(self.render_calls, [])

    def test_render_failure_is_reported_but_key_still_rotates(self) -> None:
        result = self.refresh(OLD_KEY, valid_keys={NEW_KEY}, render_ok=False)
        self.assertTrue(result.rotated)
        self.assertFalse(result.render_updated)
        self.assertEqual(result.active_key, NEW_KEY)


if __name__ == "__main__":
    unittest.main()
