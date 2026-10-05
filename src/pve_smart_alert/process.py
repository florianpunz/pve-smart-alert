# SPDX-License-Identifier: AGPL-3.0-or-later
"""Running an external program with a timeout.

External programs are started with an argument list, never through a shell,
and in their own process group, so that a timeout ends the program and
everything it started (ARCHITECTURE.md section 14).

Every component that runs a program uses this module: the transports, the
self-diagnosis and the routing check. There is no default timeout, because
how long a program may take depends on what it does: a slow notification
target is something else than a slow drive.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProcessResult:
    """What running a program left behind."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        """Whether the program ran and ended with exit status 0."""
        return self.returncode == 0 and not self.timed_out

    @property
    def lines(self) -> tuple[str, ...]:
        """The standard error of the program, line by line."""
        return tuple(line for line in self.stderr.splitlines() if line.strip())


class ProcessRunner(Protocol):
    """Runs an external program.

    A protocol so that the code that runs programs can be tested on a machine
    that has none of them: no bridge, no mail command, no `pvesh` (ADR 0014,
    ADR 0016).
    """

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = ...,
        timeout: float,
    ) -> ProcessResult: ...


def run_with_timeout(
    command: Sequence[str | Path],
    *,
    input_text: str | None = None,
    timeout: float,
) -> ProcessResult:
    """Run a program and return its output.

    A program that does not end within `timeout` is killed together with the
    process group it started; its output up to that point is returned with
    `timed_out` set.

    Raises `OSError` when the program cannot be started at all, for example
    because it does not exist or is not executable.
    """
    process = subprocess.Popen(
        [str(argument) for argument in command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # Drive data is untrusted; output that is not valid UTF-8 must not
        # end the run (ARCHITECTURE.md section 14).
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        stdout, stderr = process.communicate()
        return ProcessResult(returncode=None, stdout=stdout, stderr=stderr, timed_out=True)

    return ProcessResult(
        returncode=process.returncode, stdout=stdout, stderr=stderr, timed_out=False
    )


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    """Kill a program and everything it started."""
    # A ProcessLookupError means it ended between the timeout and the kill.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
