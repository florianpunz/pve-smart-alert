# SPDX-License-Identifier: AGPL-3.0-or-later
"""The test frame runs no program of the host (ADR 0016).

Tests need neither root nor real drives, and a test must never read the
drives of the machine it runs on. Every program the tool starts goes through
`pve_smart_alert.process.run_with_timeout`, which calls `subprocess.Popen`.
This plugin replaces that one call for every test: a program may be started
only from the test tree, where the fake smartctl lives, or from the temporary
directory of pytest, where tests write their stand-ins for lsblk, pvesh,
sendmail and the notify bridge. Anything else, such as `/usr/sbin/smartctl`
or `/usr/bin/lsblk`, fails the test loudly, also when the tool would catch
the error, because the violation is recorded and checked once the test is
done.

The tests of the process runner itself start a few harmless programs of the
host on purpose; they are marked `real_programs`.

`tests/conftest.py` imports this module; a test of the guard loads it into an
inner pytest run with `-p guard`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

import pytest

import pve_smart_alert.process as process

TESTS: Final = Path(__file__).resolve().parent

# The marker of tests that may start programs of the host.
REAL_PROGRAMS: Final = "real_programs"


class HostProgramError(AssertionError):
    """A test would start a program of the host instead of a stand-in."""


class _GuardedSubprocess:
    """What `process` sees as the module `subprocess`: the same, but a guarded `Popen`."""

    PIPE = subprocess.PIPE
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, allowed: Sequence[Path], violations: list[str]) -> None:
        self._allowed = tuple(allowed)
        self._violations = violations

    def Popen(self, command: Sequence[object], *args: object, **kwargs: object) -> object:  # noqa: N802
        program = resolved(command[0])
        if not any(program.is_relative_to(root) for root in self._allowed):
            message = (
                f"the test would run {command[0]} ({program}), a program of the host; the"
                " test frame starts only the stand-ins of the test tree and of the"
                " temporary directory (ADR 0016)"
            )
            self._violations.append(message)
            raise HostProgramError(message)
        return subprocess.Popen(command, *args, **kwargs)  # type: ignore[call-overload]


def resolved(program: object) -> Path:
    """Return the real path of a program, its links and its search path followed."""
    name = os.fspath(program)  # type: ignore[call-overload]
    if os.sep not in name:
        name = shutil.which(name) or name
    return Path(os.path.realpath(name))


@pytest.fixture(autouse=True)
def no_host_programs(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Refuse every program outside the test tree and the temporary directory."""
    if request.node.get_closest_marker(REAL_PROGRAMS) is not None:
        yield
        return
    violations: list[str] = []
    allowed = (TESTS, Path(os.path.realpath(tmp_path_factory.getbasetemp())))
    monkeypatch.setattr(process, "subprocess", _GuardedSubprocess(allowed, violations))
    yield
    if violations:
        pytest.fail("\n".join(violations), pytrace=False)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{REAL_PROGRAMS}: the test starts programs of the host on purpose,"
        " such as the tests of the process runner",
    )
