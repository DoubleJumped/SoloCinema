from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from collector.solocinema_collector import cli


@dataclass(frozen=True)
class _Summary:
    discovered: int
    checked: int
    failed: int
    database_url: str
    status: str
    errors: list[str] = field(default_factory=list)
    probe_blocked: bool = False


def _summary(
    status: str = "success",
    discovered: int = 10,
    failed: int = 0,
    errors: list[str] | None = None,
    probe_blocked: bool = False,
) -> _Summary:
    return _Summary(
        discovered=discovered,
        checked=discovered,
        failed=failed,
        database_url="sqlite:///tmp/x.sqlite",
        status=status,
        errors=errors or [],
        probe_blocked=probe_blocked,
    )


class RunAllTests(unittest.TestCase):
    def _run_all(self, landmark, cineplex, imax, extra_args=()) -> tuple[int, dict]:
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
            code = cli.main(
                ["run-all", "--database-url", "sqlite:///tmp/x.sqlite", *extra_args]
            )
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

    def test_fails_when_one_theatre_in_a_chain_failed(self) -> None:
        cineplex = lambda **_: _summary(errors=["Normanview: HTTPError: 503"])

        code, output = self._run_all(lambda **_: _summary(), cineplex, lambda **_: _summary())

        self.assertEqual(code, 1)
        self.assertEqual(output["errors"], {"cineplex": "Normanview: HTTPError: 503"})
        self.assertEqual(output["cineplex"]["discovered"], 10)
    def test_blocked_seat_probes_warn_without_failing(self) -> None:
        blocked = lambda **_: _summary("partial", probe_blocked=True)
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            code, output = self._run_all(blocked, lambda **_: _summary(), lambda **_: _summary())

        self.assertEqual(code, 0)
        self.assertNotIn("errors", output)
        self.assertIn("::warning::Atom Tickets", stderr.getvalue())

    def test_chains_limits_the_run_to_the_named_chains(self) -> None:
        def must_not_run(**_):
            raise AssertionError("chain should have been skipped")

        code, output = self._run_all(
            must_not_run, lambda **_: _summary(), must_not_run, ["--chains", "cineplex"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(list(output), ["cineplex"])

    def test_empty_chains_collects_everything(self) -> None:
        ok = lambda **_: _summary()

        code, output = self._run_all(ok, ok, ok, ["--chains", ""])

        self.assertEqual(code, 0)
        self.assertEqual(list(output), ["landmark", "cineplex", "imax"])

    def test_reports_failed_chains_to_the_workflow(self) -> None:
        def boom(**_):
            raise RuntimeError("gateway down")

        with tempfile.TemporaryDirectory() as directory:
            github_output = Path(directory) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(github_output)}):
                self._run_all(lambda **_: _summary(), boom, boom)
                first = github_output.read_text()
                github_output.write_text("")
                self._run_all(lambda **_: _summary(), lambda **_: _summary(), lambda **_: _summary())
                second = github_output.read_text()

        self.assertEqual(first, "failed_chains=cineplex,imax\n")
        self.assertEqual(second, "failed_chains=\n")


if __name__ == "__main__":
    unittest.main()
