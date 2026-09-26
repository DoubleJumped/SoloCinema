from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from unittest.mock import patch

from collector.solocinema_collector import cli


@dataclass(frozen=True)
class _Summary:
    discovered: int
    checked: int
    failed: int
    database_url: str
    status: str


def _summary(status: str = "success", discovered: int = 10, failed: int = 0) -> _Summary:
    return _Summary(
        discovered=discovered,
        checked=discovered,
        failed=failed,
        database_url="sqlite:///tmp/x.sqlite",
        status=status,
    )


class RunAllTests(unittest.TestCase):
    def _run_all(self, landmark, cineplex, imax) -> tuple[int, dict]:
        stdout = io.StringIO()
        with (
            patch(
                "collector.solocinema_collector.landmark.run_landmark_collection",
                side_effect=landmark,
            ),
            patch(
                "collector.solocinema_collector.cineplex.run_cineplex_collection",
                side_effect=cineplex,
            ),
            patch(
                "collector.solocinema_collector.imax.run_imax_collection",
                side_effect=imax,
            ),
            # Keep the hourly prune out of the way.
            patch.object(cli, "datetime") as fake_datetime,
            redirect_stdout(stdout),
        ):
            fake_datetime.now.return_value.minute = 30
            code = cli.main(["run-all", "--database-url", "sqlite:///tmp/x.sqlite"])
        return code, json.loads(stdout.getvalue())

    def test_succeeds_when_every_chain_collects(self) -> None:
        ok = lambda **_: _summary()
        partial = lambda **_: _summary("partial", failed=1)

        code, output = self._run_all(ok, partial, ok)

        self.assertEqual(code, 0)
        self.assertNotIn("errors", output)

    def test_fails_when_a_chain_raises(self) -> None:
        def boom(**_):
            raise RuntimeError("gateway down")

        code, output = self._run_all(lambda **_: _summary(), boom, lambda **_: _summary())

        self.assertEqual(code, 1)
        self.assertEqual(output["errors"], {"cineplex": "RuntimeError: gateway down"})

    def test_fails_when_a_chain_quietly_comes_back_empty(self) -> None:
        empty = lambda **_: _summary("failed", discovered=0)

        code, output = self._run_all(empty, lambda **_: _summary(), lambda **_: _summary())

        self.assertEqual(code, 1)
        self.assertIn("discovered 0", output["errors"]["landmark"])
        self.assertIn("landmark", output)


if __name__ == "__main__":
    unittest.main()
