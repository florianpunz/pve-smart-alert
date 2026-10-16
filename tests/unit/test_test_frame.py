# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the guard of the test frame (tests/guard.py, ADR 0016).

A test that would start the smartctl, lsblk, pvesh or notify bridge of the
host must fail, not just be avoided. The misconfigured tests run in an inner
pytest with the guard loaded, and these tests check that each of them fails
and says why.
"""

from __future__ import annotations

import textwrap

import pytest

pytest_plugins = ["pytester"]

# The inner pytest runs in this process and loads the guard itself. These
# tests start no program; they only watch the inner run, so the guard of the
# outer test stands aside and the inner one alone decides.
pytestmark = pytest.mark.real_programs

# The programs of an installed host that a test must never start.
HOST_PROGRAMS = """
from pathlib import Path

from pve_smart_alert.discovery.enrichment import HostPaths, read_block_devices
from pve_smart_alert.paths import BRIDGE_PATH, LSBLK_PATH, PVESH_PATH, SMARTCTL_PATH
from pve_smart_alert.process import run_with_timeout


def test_smartctl():
    run_with_timeout([SMARTCTL_PATH, "--version"], timeout=5)


def test_lsblk_through_the_enrichment_that_catches_errors():
    # The enrichment reports an error instead of raising; the guard fails
    # the test all the same.
    read_block_devices(HostPaths(lsblk=LSBLK_PATH))


def test_pvesh():
    # Called directly: the doctor asks for pvesh only where it is installed.
    run_with_timeout([PVESH_PATH, "get", "/cluster/notifications/matchers"], timeout=5)


def test_the_notify_bridge():
    run_with_timeout([BRIDGE_PATH, "--check"], timeout=5)


def test_a_program_found_through_the_search_path():
    run_with_timeout(["smartctl", "--version"], timeout=5)


def test_a_link_from_the_temporary_directory_to_the_host(tmp_path):
    link = tmp_path / "smartctl"
    link.symlink_to(SMARTCTL_PATH)
    run_with_timeout([link, "--version"], timeout=5)
"""

STAND_INS = """
import sys
from pathlib import Path

from guard import TESTS
from pve_smart_alert.process import run_with_timeout


def test_the_fake_smartctl_of_the_test_tree():
    result = run_with_timeout([TESTS / "fake-smartctl", "--version"], timeout=10)
    assert result.timed_out is False


def test_a_stand_in_in_the_temporary_directory(tmp_path):
    program = tmp_path / "pvesh"
    program.write_text("#!/bin/sh\\necho stand-in\\n", encoding="utf-8")
    program.chmod(0o755)
    assert run_with_timeout([program], timeout=10).stdout == "stand-in\\n"
"""


def run_inner(pytester: pytest.Pytester, source: str) -> pytest.RunResult:
    pytester.makepyfile(test_inner=textwrap.dedent(source))
    return pytester.runpytest(
        "-p", "guard", "-p", "no:cacheprovider", "-W", "ignore::pytest.PytestAssertRewriteWarning"
    )


def test_every_program_of_the_host_fails_its_test(pytester: pytest.Pytester) -> None:
    result = run_inner(pytester, HOST_PROGRAMS)

    # Each of the six tests fails in its call, and once more when it is done,
    # where the guard checks what it recorded: also an error that the tool
    # caught would fail the test there.
    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) == 0
    assert outcomes.get("failed") == 6
    assert outcomes.get("errors") == 6
    output = result.stdout.str()
    for program in (
        "/usr/sbin/smartctl",
        "/usr/bin/lsblk",
        "/usr/bin/pvesh",
        "/usr/libexec/pve-smart-alert/notify-bridge",
    ):
        assert f"({program}), a program of the host" in output


def test_the_stand_ins_of_the_test_tree_and_the_temporary_directory_run(
    pytester: pytest.Pytester,
) -> None:
    result = run_inner(pytester, STAND_INS)

    result.assert_outcomes(passed=2)


def test_a_test_marked_for_real_programs_may_start_them(pytester: pytest.Pytester) -> None:
    result = run_inner(
        pytester,
        """
        import pytest

        from pve_smart_alert.process import run_with_timeout


        @pytest.mark.real_programs
        def test_true():
            assert run_with_timeout(["true"], timeout=5).ok
        """,
    )

    result.assert_outcomes(passed=1)
