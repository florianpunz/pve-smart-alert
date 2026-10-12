# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the systemd units and the failure reporter (ADR 0006, FR-519).

The units are read as the key files they are. The failure reporter runs as
the shell script it is, with a mail command and a journal that the test
provides.
"""

from __future__ import annotations

import configparser
import os
import subprocess
from pathlib import Path

import pytest

from pve_smart_alert import cli

REPOSITORY = Path(__file__).resolve().parents[2]
UNITS = REPOSITORY / "systemd"
REPORTER = REPOSITORY / "libexec" / "report-failure"
INSTALL = REPOSITORY / "debian" / "pve-smart-alert.install"


def unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(UNITS / name, encoding="utf-8")
    return parser


def installed_path(source: str) -> str:
    """Return where the package installs a file of the repository."""
    for line in INSTALL.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and not line.startswith("#"):
            pattern, target = parts
            if Path(source).match(pattern):
                return f"/{target}/{Path(source).name}"
    raise AssertionError(f"{source} is not installed")


def test_the_timer_runs_every_thirty_minutes() -> None:
    # ADR 0006: monotonic, first run three minutes after boot.
    timer = unit("pve-smart-alert.timer")

    assert dict(timer["Timer"]) == {
        "OnBootSec": "3min",
        "OnUnitActiveSec": "30min",
        "AccuracySec": "1min",
    }
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_the_service_runs_one_check() -> None:
    service = unit("pve-smart-alert.service")["Service"]

    assert service["Type"] == "oneshot"
    assert service["ExecStart"] == f"{installed_path('libexec/pve-smart-alert')} check"
    # A run skipped because another holds the lock is no failure (FR-605).
    assert service["SuccessExitStatus"] == str(cli.EXIT_LOCKED)
    # The run-time limit of NFR-08 and the priorities of NFR-09.
    assert service["TimeoutStartSec"] == "15min"
    assert service["Nice"] == "10"
    assert service["IOSchedulingClass"] == "best-effort"
    assert service["StateDirectory"] == "pve-smart-alert"
    assert service["StateDirectoryMode"] == "0700"


def test_the_service_is_ordered_after_pmxcfs_without_needing_it() -> None:
    # ADR 0006: without pmxcfs the check runs and the fallback is used.
    section = unit("pve-smart-alert.service")["Unit"]

    assert section["After"] == "pve-cluster.service"
    assert "Requires" not in section
    assert "BindsTo" not in section


def test_a_failed_run_starts_the_failure_reporter() -> None:
    service = unit("pve-smart-alert.service")
    failure = unit("pve-smart-alert-failure.service")

    assert service["Unit"]["OnFailure"] == "pve-smart-alert-failure.service"
    assert failure["Service"]["ExecStart"] == installed_path("libexec/report-failure")


@pytest.mark.parametrize("name", ["pve-smart-alert.service", "pve-smart-alert-failure.service"])
def test_only_the_timer_is_enabled(name: str) -> None:
    # The services are started by the timer and by OnFailure=, never by an
    # installation (ADR 0013).
    assert not unit(name).has_section("Install")
    rules = (REPOSITORY / "debian" / "rules").read_text(encoding="utf-8")
    assert "dh_installsystemd pve-smart-alert.timer" in rules


@pytest.fixture
def reporter(tmp_path: Path) -> dict[str, str]:
    """An environment for the failure reporter: a mail command and a journal of the test."""
    mail = tmp_path / "mail.txt"
    sendmail = tmp_path / "sendmail"
    sendmail.write_text(f'#!/bin/sh\necho "$@" > "{mail}.args"\ncat > "{mail}"\n', "utf-8")
    sendmail.chmod(0o755)
    journal = tmp_path / "journalctl"
    journal.write_text("#!/bin/sh\necho 'Traceback (most recent call last):'\n", "utf-8")
    journal.chmod(0o755)
    return {
        **os.environ,
        "PVE_SMART_ALERT_RUN_DIR": str(tmp_path / "run"),
        "PVE_SMART_ALERT_SENDMAIL": str(sendmail),
        "PVE_SMART_ALERT_JOURNALCTL": str(journal),
    }


def report(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPORTER)], env=environment, capture_output=True, text=True, check=False
    )


def test_a_failure_is_reported_as_mail_to_root(reporter: dict[str, str], tmp_path: Path) -> None:
    result = report(reporter)

    assert result.returncode == 0
    mail = (tmp_path / "mail.txt").read_text(encoding="utf-8")
    assert mail.startswith("To: root\n")
    assert "Subject: [pve-smart-alert] ERROR " in mail
    assert "Traceback (most recent call last):" in mail
    assert "journalctl -u pve-smart-alert.service" in mail
    assert (tmp_path / "mail.txt.args").read_text(encoding="utf-8").split() == ["-i", "-t"]


def test_a_failure_is_reported_at_most_once_per_day(
    reporter: dict[str, str], tmp_path: Path
) -> None:
    # FR-519.
    report(reporter)
    (tmp_path / "mail.txt").unlink()

    again = report(reporter)

    assert again.returncode == 0
    assert "already reported today" in again.stdout
    assert not (tmp_path / "mail.txt").exists()


def test_a_report_of_another_day_does_not_hold_back_today(
    reporter: dict[str, str], tmp_path: Path
) -> None:
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "failure-reported").write_text("2000-01-01\n", encoding="utf-8")

    report(reporter)

    assert (tmp_path / "mail.txt").exists()


def test_a_mail_that_was_not_taken_is_tried_again(reporter: dict[str, str], tmp_path: Path) -> None:
    broken = tmp_path / "broken-sendmail"
    broken.write_text("#!/bin/sh\ncat > /dev/null\nexit 75\n", encoding="utf-8")
    broken.chmod(0o755)

    failed = report({**reporter, "PVE_SMART_ALERT_SENDMAIL": str(broken)})

    assert failed.returncode == 1
    assert not (tmp_path / "run" / "failure-reported").exists()
