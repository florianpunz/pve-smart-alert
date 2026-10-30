# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the command-line interface."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

import pytest

import pve_smart_alert.process as process
from pve_smart_alert import __version__
from pve_smart_alert.cli import main
from pve_smart_alert.doctor import CheckResult


def test_version_option_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"pve-smart-alert {__version__}"


def test_without_arguments_the_help_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    out = capsys.readouterr().out
    assert "usage:" in out
    assert "--version" in out


def test_module_entry_point_prints_the_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pve_smart_alert", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == f"pve-smart-alert {__version__}"


def _status_of_interrupted(arguments: Sequence[str]) -> int:
    """Run a command and report its status; an escaping interrupt is a failure.

    Without the handler an uncaught `KeyboardInterrupt` ends the whole pytest
    session, so the test would stop the run instead of failing on its own line.
    """
    try:
        return main(list(arguments))
    except KeyboardInterrupt:
        pytest.fail(
            f"the interrupt escaped {' '.join(arguments)} instead of ending it with a status"
        )


def test_an_interrupted_command_ends_with_a_line_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ctrl+C during `doctor`, as it happened on `pve1` on 2026-10-18."""

    def interrupted() -> list[CheckResult]:
        raise KeyboardInterrupt

    monkeypatch.setattr("pve_smart_alert.cli.run_doctor", interrupted)

    assert _status_of_interrupted(["doctor"]) == 130

    captured = capsys.readouterr()
    assert captured.err.strip() == "pve-smart-alert: interrupted"
    assert captured.out == ""
    assert "Traceback" not in captured.err


class _InterruptedProcess:
    """A started program whose wait is interrupted, as `pvesh` was on `pve1`."""

    returncode: int | None = None

    def communicate(self, *_arguments: object, **_keywords: object) -> tuple[str, str]:
        raise KeyboardInterrupt


class _InterruptedSubprocess:
    """What `process` sees as the module `subprocess`: every start is interrupted."""

    PIPE = process.subprocess.PIPE  # type: ignore[attr-defined]
    TimeoutExpired = process.subprocess.TimeoutExpired  # type: ignore[attr-defined]

    def __init__(self) -> None:
        self.started: list[list[str]] = []

    def Popen(  # noqa: N802
        self, command: list[str], *_arguments: object, **_keywords: object
    ) -> _InterruptedProcess:
        self.started.append(list(command))
        return _InterruptedProcess()


def test_an_interrupt_while_the_arguments_are_read_ends_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The handler covers the argument parser too, not only the command."""

    def interrupted(
        _self: argparse.ArgumentParser, _arguments: object = None
    ) -> argparse.Namespace:
        raise KeyboardInterrupt

    monkeypatch.setattr("argparse.ArgumentParser.parse_args", interrupted)

    assert _status_of_interrupted(["doctor"]) == 130

    captured = capsys.readouterr()
    assert captured.err.strip() == "pve-smart-alert: interrupted"
    assert captured.out == ""
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "arguments",
    [
        ["test-notification"],
        ["doctor"],
        ["scan"],
        ["check"],
        ["check", "--dry-run"],
        ["status"],
        ["config", "check"],
        ["config", "show"],
        ["dump-fixture", "--all"],
    ],
)
def test_every_command_ends_with_the_line_when_it_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    """A handler that only wrapped one command would pass a test of that one."""

    def interrupted(*_arguments: object, **_keywords: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr("pve_smart_alert.cli._run", interrupted)

    assert _status_of_interrupted(arguments) == 130

    captured = capsys.readouterr()
    assert captured.err.strip() == "pve-smart-alert: interrupted"
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_an_interrupt_inside_the_program_that_runs_ends_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The interrupt on `pve1` came out of `pvesh`, so out of the process runner."""
    interrupted = _InterruptedSubprocess()
    monkeypatch.setattr("pve_smart_alert.process.subprocess", interrupted)

    def doctor_that_reads_pvesh() -> list[CheckResult]:
        process.run_with_timeout(
            ("/usr/bin/pvesh", "get", "/cluster/notifications/matchers"),
            timeout=30.0,
        )
        return []

    monkeypatch.setattr("pve_smart_alert.cli.run_doctor", doctor_that_reads_pvesh)

    assert _status_of_interrupted(["doctor"]) == 130

    # The call really went through the runner, which is where the interrupt
    # came from; the handler above it is not what this test stands for.
    assert interrupted.started == [["/usr/bin/pvesh", "get", "/cluster/notifications/matchers"]]
    captured = capsys.readouterr()
    assert captured.err.strip() == "pve-smart-alert: interrupted"
    assert captured.out == ""
