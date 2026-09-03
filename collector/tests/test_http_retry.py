from __future__ import annotations

import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from collector.solocinema_collector import http_retry
from collector.solocinema_collector.http_retry import (
    RetryBudget,
    open_with_retry,
    retry_after_seconds,
)


def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://example.test/x", code, "err", headers, None)


class OpenWithRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.budget = RetryBudget()
        sleep_patch = patch.object(http_retry.time, "sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def _slept(self) -> list[float]:
        return [call.args[0] for call in self.sleep.call_args_list]

    def test_returns_first_success_without_sleeping(self) -> None:
        result = open_with_retry(lambda: "ok", self.budget)

        self.assertEqual(result, "ok")
        self.sleep.assert_not_called()

    def test_retries_each_transient_status(self) -> None:
        for code in sorted(http_retry.RETRY_STATUSES):
            with self.subTest(code=code):
                self.budget.reset()
                calls = iter([_http_error(code), "ok"])

                def perform():
                    value = next(calls)
                    if isinstance(value, HTTPError):
                        raise value
                    return value

                self.assertEqual(open_with_retry(perform, self.budget), "ok")

    def test_does_not_retry_an_auth_failure(self) -> None:
        attempts = 0

        def perform():
            nonlocal attempts
            attempts += 1
            raise _http_error(401)

        with self.assertRaises(HTTPError):
            open_with_retry(perform, self.budget)

        self.assertEqual(attempts, 1)
        self.sleep.assert_not_called()

    def test_retries_network_errors_that_never_reached_the_server(self) -> None:
        for error in (URLError("connection reset"), TimeoutError("timed out")):
            with self.subTest(error=type(error).__name__):
                self.budget.reset()
                calls = iter([error, "ok"])

                def perform():
                    value = next(calls)
                    if isinstance(value, BaseException):
                        raise value
                    return value

                self.assertEqual(open_with_retry(perform, self.budget), "ok")

    def test_backs_off_then_raises_when_the_outage_persists(self) -> None:
        attempts = 0

        def perform():
            nonlocal attempts
            attempts += 1
            raise _http_error(503)

        with self.assertRaises(HTTPError):
            open_with_retry(perform, self.budget)

        self.assertEqual(attempts, len(http_retry.RETRY_DELAYS_SECONDS) + 1)
        self.assertEqual(self._slept(), list(http_retry.RETRY_DELAYS_SECONDS))

    def test_prefers_the_retry_after_header(self) -> None:
        calls = iter([_http_error(429, retry_after="9"), "ok"])

        def perform():
            value = next(calls)
            if isinstance(value, HTTPError):
                raise value
            return value

        open_with_retry(perform, self.budget)

        self.assertEqual(self._slept(), [9.0])

    def test_budget_caps_total_backoff_across_a_sustained_outage(self) -> None:
        def perform():
            raise _http_error(403)

        for _ in range(200):
            with self.assertRaises(HTTPError):
                open_with_retry(perform, self.budget)

        self.assertLessEqual(sum(self._slept()), http_retry.DEFAULT_BUDGET_SECONDS)
        self.assertGreater(sum(self._slept()), 0)

    def test_before_attempt_runs_for_retries_too(self) -> None:
        throttled = 0

        def before_attempt() -> None:
            nonlocal throttled
            throttled += 1

        calls = iter([_http_error(503), _http_error(503), "ok"])

        def perform():
            value = next(calls)
            if isinstance(value, HTTPError):
                raise value
            return value

        open_with_retry(perform, self.budget, before_attempt=before_attempt)

        self.assertEqual(throttled, 3)


class RetryAfterTests(unittest.TestCase):
    def test_parses_caps_and_ignores_unusable_values(self) -> None:
        self.assertEqual(retry_after_seconds(_http_error(429, "7")), 7.0)
        self.assertEqual(
            retry_after_seconds(_http_error(429, "999")),
            http_retry.RETRY_AFTER_CAP_SECONDS,
        )
        self.assertIsNone(retry_after_seconds(_http_error(429)))
        # HTTP-date form is legal but rare; treat it as absent rather than crash.
        self.assertIsNone(retry_after_seconds(_http_error(429, "Wed, 21 Oct 2026 07:28:00 GMT")))


class RetryBudgetTests(unittest.TestCase):
    def test_refuses_a_sleep_it_cannot_afford_and_resets(self) -> None:
        budget = RetryBudget(10.0)
        with patch.object(http_retry.time, "sleep") as sleep:
            self.assertTrue(budget.spend(6.0))
            self.assertFalse(budget.spend(6.0))
            self.assertEqual(sleep.call_count, 1)
            budget.reset()
            self.assertTrue(budget.spend(6.0))


if __name__ == "__main__":
    unittest.main()
