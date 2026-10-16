# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for running an external program with a timeout (ARCHITECTURE.md 14)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from pve_smart_alert.process import run_with_timeout

# These tests are about the runner itself, so they start harmless programs
# of the host on purpose (tests/guard.py).
pytestmark = pytest.mark.real_programs

# Long enough for any program of these tests, short enough to end a hanging
# test run. The tests of the timeout itself use a shorter one.
TIMEOUT = 10.0


def program_has_ended(pid: int) -> bool:
    """Wait for a process to disappear and report whether it did."""
    for _ in range(200):
        try:
            # Signal 0 sends nothing, it only asks whether the process exists.
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.01)
    return False


def test_output_and_exit_status_are_returned() -> None:
    result = run_with_timeout(["/bin/sh", "-c", "echo out; echo err >&2; exit 3"], timeout=TIMEOUT)

    assert result.returncode == 3
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.timed_out is False
    assert result.ok is False


def test_a_successful_program_is_ok() -> None:
    result = run_with_timeout(["/bin/true"], timeout=TIMEOUT)

    assert result.ok is True
    assert result.returncode == 0
    assert result.lines == ()


def test_the_input_reaches_the_program() -> None:
    result = run_with_timeout(["/bin/cat"], input_text="hello\n", timeout=TIMEOUT)

    assert result.stdout == "hello\n"
    assert result.ok is True


def test_only_lines_with_text_are_log_lines() -> None:
    writer = "import sys; n = chr(10); sys.stderr.write('one' + n + n + '  ' + n + 'two' + n)"

    result = run_with_timeout([sys.executable, "-c", writer], timeout=TIMEOUT)

    assert result.lines == ("one", "two")


def test_output_that_is_not_utf8_is_replaced() -> None:
    # Drive data is untrusted, it must not end the run.
    writer = "import sys; sys.stdout.buffer.write(bytes([97, 255, 98]))"

    result = run_with_timeout([sys.executable, "-c", writer], timeout=TIMEOUT)

    assert result.stdout == "a�b"


def test_a_missing_program_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_with_timeout([tmp_path / "absent"], timeout=TIMEOUT)


def test_a_program_that_is_not_executable_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "not-executable"
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(PermissionError):
        run_with_timeout([path], timeout=TIMEOUT)


def test_arguments_are_not_interpreted_by_a_shell(tmp_path: Path) -> None:
    marker = tmp_path / "touched"
    argument = f"; touch {marker}; echo"

    result = run_with_timeout(["/bin/echo", argument], timeout=TIMEOUT)

    assert result.stdout.strip() == argument
    assert not marker.exists()


def test_the_program_runs_in_its_own_process_group() -> None:
    printer = "import os; print(os.getpgrp())"

    result = run_with_timeout([sys.executable, "-c", printer], timeout=TIMEOUT)

    # Without its own group a timeout would end this test run as well.
    assert int(result.stdout.strip()) != os.getpgrp()


def test_a_timeout_is_reported() -> None:
    sleeper = "import time; time.sleep(30)"

    result = run_with_timeout([sys.executable, "-c", sleeper], timeout=2.0)

    assert result.timed_out is True
    assert result.returncode is None
    assert result.ok is False


def test_a_timeout_kills_what_the_program_started() -> None:
    starter = (
        "import subprocess, sys\n"
        "child = subprocess.Popen(['/bin/sleep', '30'])\n"
        "print(child.pid, flush=True)\n"
        "child.wait()\n"
    )

    result = run_with_timeout([sys.executable, "-c", starter], timeout=2.0)

    assert result.timed_out is True
    assert program_has_ended(int(result.stdout.strip())) is True
