# SPDX-License-Identifier: AGPL-3.0-or-later
"""The acceptance steps of milestone M4, as scenario tests (ROADMAP.md, ADR 0016).

Each step of ROADMAP.md, "M4: State and notification policy", "Result you
can test", runs `pve-smart-alert check` once per step of a scenario of
`tests/scenarios.py`, against the fake smartctl, with an injected clock, a
temporary state directory and a recording transport. The same steps are run
on a real host with `python3 tests/scenarios.py build` afterwards.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from frame import ScenarioHost

from pve_smart_alert import cli
from pve_smart_alert.model import (
    FIELD_DEVICE,
    FIELD_EVENT,
    FIELD_SERIAL,
    PVE_SEVERITY,
    EventType,
    Notification,
    PveSeverity,
    Severity,
)


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScenarioHost:
    scenario = ScenarioHost(tmp_path, monkeypatch, "pending-sectors")
    scenario.install()
    return scenario


def status(capsys: pytest.CaptureFixture[str]) -> str:
    """Return what `pve-smart-alert status` prints now (acceptance step 9)."""
    capsys.readouterr()
    assert cli.main(["status"]) == cli.EXIT_OK
    return capsys.readouterr().out


def only(notifications: list[Notification]) -> Notification:
    assert len(notifications) == 1, [n.subject for n in notifications]
    return notifications[0]


def test_the_ten_steps_of_m4(host: ScenarioHost, capsys: pytest.CaptureFixture[str]) -> None:
    # 1. First run: exactly one summary notification that lists all drives.
    summary = only(host.run("01-healthy"))
    assert summary.event is EventType.FIRST_RUN
    assert summary.severity is Severity.INFO
    assert "/dev/sda [sat] Intenso SSD (ANON-SN-0001)" in summary.body
    assert host.exit_status == cli.EXIT_OK
    assert "no active conditions" in status(capsys)

    # 2. Second run without change: nothing.
    assert host.run("02-healthy") == []

    # 3. "3 pending sectors": one notification, warning, naming drive, value
    #    and threshold.
    warning = only(host.run("03-pending-3"))
    assert PVE_SEVERITY[warning.severity] is PveSeverity.WARNING
    assert warning.event is EventType.PROBLEM
    assert "/dev/sda Intenso SSD (ANON-SN-0001): 3 pending sectors" in warning.subject
    assert "Pending sectors: 3" in warning.body
    assert "Thresholds: warning 1, critical 16" in warning.body
    assert warning.fields_for()[FIELD_SERIAL] == "ANON-SN-0001"
    assert "WARNING   ata.pending_sectors" in status(capsys)

    # 4. The same step again: nothing.
    assert host.run("04-pending-3") == []

    # 5. "20 pending sectors": one notification, error, marked as escalated.
    error = only(host.run("05-pending-20"))
    assert PVE_SEVERITY[error.severity] is PveSeverity.ERROR
    assert error.event is EventType.ESCALATED
    assert error.fields_for()[FIELD_EVENT] == "escalated"
    assert "escalated from warning" in error.body
    assert "Pending sectors: 20 (previous: 3)" in error.body
    assert "CRITICAL  ata.pending_sectors" in status(capsys)

    # 6. "Healthy again", twice: one recovery notification.
    assert host.run("06-healthy") == []
    assert "CRITICAL  ata.pending_sectors" in status(capsys)
    recovery = only(host.run("07-healthy"))
    assert recovery.event is EventType.RECOVERED
    assert PVE_SEVERITY[recovery.severity] is PveSeverity.INFO
    assert "ata.pending_sectors" not in status(capsys)

    # 7. "Drive gone", twice: one notification about the missing drive.
    assert host.run("08-gone") == []
    assert "not found in 1 run" in status(capsys)
    missing = only(host.run("09-gone"))
    assert missing.event is EventType.MISSING
    assert PVE_SEVERITY[missing.severity] is PveSeverity.WARNING
    assert missing.fields_for()[FIELD_DEVICE] == "/dev/sda"
    assert "missing, notified" in status(capsys)
    assert host.run("09-gone") == []

    # Every run completed, whatever the health of the drive (FR-607).
    assert host.exit_status == cli.EXIT_OK


def test_five_drives_too_hot_are_one_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 8. "Five drives too hot": one summary notification instead of five.
    host = ScenarioHost(tmp_path, monkeypatch, "five-hot")
    host.install()

    first = only(host.run("01-cool"))
    waiting = host.run("02-hot")
    hot = only(host.run("03-hot"))

    assert first.event is EventType.FIRST_RUN
    assert waiting == []
    assert "temperature" in status(capsys)
    assert hot.event is EventType.SUMMARY
    assert hot.subject == "[pve-smart-alert] WARNING pve1: 5 drives need attention"
    for number in range(1, 6):
        assert f"ANON-SN-000{number}" in hot.body
    # A summary carries no metadata of a single drive (ADR 0009).
    assert FIELD_SERIAL not in hot.fields_for()
    assert host.run("03-hot") == []


def test_a_deleted_state_file_leads_to_one_summary(host: ScenarioHost) -> None:
    # 10. Deleting the state file leads to one summary on the next run, not
    #     to individual alerts.
    host.run("01-healthy")
    host.run("03-pending-3")
    host.state_path.unlink()

    after = only(host.run("05-pending-20"))

    assert after.event is EventType.FIRST_RUN
    assert "ata.pending_sectors" in after.body


def test_status_shows_the_active_conditions_as_json(
    host: ScenarioHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # 9, machine-readable (FR-602).
    host.run("01-healthy")
    host.run("03-pending-3")
    capsys.readouterr()

    assert cli.main(["status", "--json"]) == cli.EXIT_OK

    document = json.loads(capsys.readouterr().out)
    (drive,) = document["drives"].values()
    assert drive["conditions"]["ata.pending_sectors"]["severity"] == "warning"
    assert document["last_run"]["result"] == "ok"


def test_status_without_a_state(host: ScenarioHost, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["status"]) == cli.EXIT_OK
    assert "does not exist yet" in capsys.readouterr().out
    assert not host.state_path.exists()


# What a run guarantees besides the ten steps


def test_a_corrupt_state_file_is_set_aside_and_reported_once(host: ScenarioHost) -> None:
    # NFR-12: the run continues, and the following notification is a summary.
    host.run("01-healthy")
    host.state_path.write_text("{broken", encoding="utf-8")

    after = only(host.run("03-pending-3"))

    assert after.event is EventType.FIRST_RUN
    assert "set aside" in after.body
    assert any(path.name.startswith("state.json.corrupt-") for path in host.state_dir.iterdir())
    assert host.run("03-pending-3") == []


def test_a_notification_that_fails_is_sent_on_the_next_run(host: ScenarioHost) -> None:
    # FR-517, FR-607: the state is not advanced, and the run fails.
    host.run("01-healthy")
    host.transport.failing = True

    assert host.run("03-pending-3") == []
    assert host.exit_status == cli.EXIT_PROBLEM

    host.transport.failing = False
    retried = only(host.run("03-pending-3"))
    assert retried.event is EventType.PROBLEM
    assert host.exit_status == cli.EXIT_OK


def test_a_reminder_follows_after_seven_days(host: ScenarioHost) -> None:
    host.run("01-healthy")
    host.run("03-pending-3")

    early = host.run("03-pending-3", advance=timedelta(days=6))
    due = only(host.run("03-pending-3", advance=timedelta(days=1)))

    assert early == []
    assert due.event is EventType.REMINDER


def test_a_second_run_while_one_holds_the_lock_is_skipped(
    host: ScenarioHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # FR-605.
    lock = host.lock_path
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        assert cli.main(["check"]) == cli.EXIT_LOCKED
    finally:
        os.close(descriptor)

    assert "another run holds the lock" in capsys.readouterr().err
    assert not host.state_path.exists()


def test_a_run_logs_one_summary_line(
    host: ScenarioHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # FR-606.
    host.run("01-healthy")
    capsys.readouterr()
    host.run("03-pending-3")

    lines = [
        line for line in capsys.readouterr().out.splitlines() if line.startswith("pve-smart-alert:")
    ]

    assert lines == [
        "pve-smart-alert: run ok: 1 drives evaluated, 0 skipped, 0 failed; active conditions:"
        " 0 critical, 1 warning, 0 notice; 1 notifications sent, 0 not delivered"
    ]


def test_the_dry_run_changes_nothing(
    host: ScenarioHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # FR-601.
    host.run("01-healthy")
    before = host.state_path.read_text(encoding="utf-8")
    host.step("03-pending-3")
    capsys.readouterr()

    assert cli.main(["check", "--dry-run"]) == cli.EXIT_PROBLEM

    out = capsys.readouterr().out
    assert "problem    [pve-smart-alert] WARNING pve1: /dev/sda" in out
    assert host.transport.take() == []
    assert host.state_path.read_text(encoding="utf-8") == before


def test_an_unreadable_drive_is_reported_after_two_runs(host: ScenarioHost) -> None:
    # FR-310, with the fake smartctl answering without usable data.
    host.run("01-healthy")
    host.behave("sda.json", stdout="not json", exit_status=0)

    first = host.run()
    second = only(host.run())

    assert first == []
    assert second.event is EventType.PROBLEM
    assert "drive.unreadable" in second.body
    assert "ANON-SN-0001" in second.body


def test_a_missing_smartctl_is_a_problem_of_the_tool(host: ScenarioHost) -> None:
    # FR-518: the conditions of the tool follow the same policy.
    host.run("01-healthy")
    host.config_path.write_text('[smartctl]\npath = "/nonexistent/smartctl"\n', encoding="utf-8")

    problem = only(host.run())
    quiet = host.run()

    assert problem.event is EventType.TOOL
    assert problem.fields_for()[FIELD_DEVICE] == "pve-smart-alert"
    assert "smartctl missing" in problem.subject
    assert quiet == []
    # Without smartctl, nothing was looked for: the drive is not missing.
    assert host.run() == []


def test_an_invalid_configuration_is_a_problem_of_the_tool(host: ScenarioHost) -> None:
    host.run("01-healthy")
    text = host.config_path.read_text(encoding="utf-8")
    host.config_path.write_text(text + "[notify]\nnotise = 1\n", encoding="utf-8")

    problem = only(host.run())

    assert "configuration invalid" in problem.subject
    assert "the last good configuration" in " ".join(problem.body.split())
