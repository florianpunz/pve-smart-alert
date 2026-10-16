# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the scenario frame (ADR 0016).

The steps of every scenario are recordings the fake smartctl replays, and
each step shows the host the scenario says it shows. The clock and the
recording transport of the frame do what the scenario tests rely on.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from frame import RUN_INTERVAL, START, Clock, RecordingTransport, ScenarioHost

from pve_smart_alert.checks import evaluate
from pve_smart_alert.discovery import Outcome, SkipReason
from pve_smart_alert.model import (
    FIELD_DEVICE,
    FIELD_DEVICE_ID,
    FIELD_SERIAL,
    EventType,
    Notification,
    Severity,
)
from scenarios import SCENARIOS, main


def findings_of(host: ScenarioHost) -> dict[str, list[tuple[str, Severity, int | None]]]:
    """Return the findings of every monitored drive of the current step, by device."""
    result = {}
    for found in host.discover().monitored:
        assert found.snapshot is not None
        result[found.candidate.name] = [
            (finding.check, finding.severity, finding.value) for finding in evaluate(found.snapshot)
        ]
    return result


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_step_of_every_scenario_is_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    host = ScenarioHost(tmp_path, monkeypatch, name)
    for step in host.scenario.steps:
        host.step(step.name)
        discovery = host.discover()
        assert discovery.scan_error is None
        assert all(found.outcome is not Outcome.UNREADABLE for found in discovery.devices)


def test_the_pending_sectors_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = ScenarioHost(tmp_path, monkeypatch, "pending-sectors")

    assert findings_of(host) == {"/dev/sda": []}
    host.step("03-pending-3")
    assert findings_of(host) == {"/dev/sda": [("ata.pending_sectors", Severity.WARNING, 3)]}
    host.step("05-pending-20")
    assert findings_of(host) == {"/dev/sda": [("ata.pending_sectors", Severity.CRITICAL, 20)]}
    host.step("07-healthy")
    assert findings_of(host) == {"/dev/sda": []}
    host.step("09-gone")
    assert findings_of(host) == {}


def test_the_five_hot_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = ScenarioHost(tmp_path, monkeypatch, "five-hot")

    cool = findings_of(host)
    assert sorted(cool) == [f"/dev/sd{letter}" for letter in "abcde"]
    assert all(findings == [] for findings in cool.values())
    serials = {
        found.snapshot.identity.serial for found in host.discover().monitored if found.snapshot
    }
    assert serials == {f"ANON-SN-{number:04d}" for number in range(1, 6)}

    host.step("02-hot")
    hot = findings_of(host)
    assert all(findings == [("temperature", Severity.WARNING, 65)] for findings in hot.values())


def megaraid_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> ScenarioHost:
    """A MegaRAID scenario, installed, with the controller as SCSI host 6 of `megaraid_sas`."""
    host = ScenarioHost(tmp_path, monkeypatch, name)
    host.install()
    host.scsi_host(6, "megaraid_sas")
    return host


def only(notifications: list[Notification]) -> Notification:
    assert len(notifications) == 1, [n.subject for n in notifications]
    return notifications[0]


def test_the_megaraid_jbod_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A drive in JBOD mode is a block device and is reached through the
    # controller as well: it is kept once, as the block device (FR-106).
    host = megaraid_host(tmp_path, monkeypatch, "megaraid-jbod")

    devices = {
        (found.candidate.name, found.candidate.type): found for found in host.discover().devices
    }
    volume = devices["/dev/sda", "scsi"]
    assert volume.reason is SkipReason.LOGICAL_VOLUME
    kept = devices["/dev/sdc", "sat"]
    assert kept.outcome is Outcome.MONITORED
    assert kept.snapshot is not None
    assert kept.snapshot.access.aliases == ("/dev/bus/6",)
    duplicate = devices["/dev/bus/6", "sat+megaraid,14"]
    assert duplicate.reason is SkipReason.DUPLICATE
    assert duplicate.detail == "the same drive as /dev/sdc"
    assert devices["/dev/bus/6", "megaraid,8"].outcome is Outcome.MONITORED

    first = only(host.run("01-first"))
    assert first.subject == "[pve-smart-alert] INFO pve1: monitoring 2 drives, no findings"
    assert FIELD_DEVICE_ID not in first.fields_for()
    assert "/dev/sdc [sat] ST6000NM0115-1YZ110 (ANON-SN-0001)  no findings" in first.body
    assert "/dev/bus/6 [megaraid,8] SEAGATE ST600MP0036 (ANON-SN-0002)  no findings" in first.body
    assert "/dev/sda [scsi]: logical-volume (lsblk vendor DELL, model PERC H730P Mini)" in (
        first.body
    )
    assert host.run("02-again") == []


def test_the_megaraid_id_change_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A drive whose device ID changes keeps its identity and its state: no
    # new problem, no missing drive (ADR 0005, FR-105).
    host = megaraid_host(tmp_path, monkeypatch, "megaraid-id-change")

    assert only(host.run("01-first")).event is EventType.FIRST_RUN
    warning = only(host.run("02-pending-8"))
    assert warning.event is EventType.PROBLEM
    assert "Location:   /dev/bus/6 (megaraid_sas), device 14" in warning.body
    assert warning.fields_for()[FIELD_DEVICE_ID] == "14"
    keys = set(json.loads(host.state_path.read_text(encoding="utf-8"))["drives"])

    assert host.run("03-moved") == []
    assert host.run("04-moved") == []
    assert host.run("04-moved", advance=timedelta(hours=6)) == []

    drives = json.loads(host.state_path.read_text(encoding="utf-8"))["drives"]
    assert (
        set(drives)
        == keys
        == {
            "ST6000NM0115-1YZ110|ANON-SN-0001",
            "SEAGATE ST600MP0036|ANON-SN-0002",
        }
    )
    sata, sas = (
        drives["ST6000NM0115-1YZ110|ANON-SN-0001"],
        drives["SEAGATE ST600MP0036|ANON-SN-0002"],
    )
    assert sata["last_access"] == {"name": "/dev/bus/6", "type": "sat+megaraid,15"}
    assert sata["details"]["location"] == "/dev/bus/6 (megaraid_sas), device 15"
    assert sata["conditions"]["ata.pending_sectors"]["first_detected"] == "2026-10-12T09:00:00Z"
    assert sas["last_access"] == {"name": "/dev/bus/6", "type": "megaraid,9"}
    assert sas["missing_runs"] == 0
    assert host.exit_status == 0

    # A missing drive carries the device ID of its last read, from the state;
    # `serial` is what still selects it (ADR 0029).
    assert host.run("05-gone") == []
    missing = only(host.run("06-gone"))
    assert missing.event is EventType.MISSING
    fields = missing.fields_for()
    assert fields[FIELD_DEVICE] == "/dev/bus/6"
    assert fields[FIELD_DEVICE_ID] == "9"
    assert fields[FIELD_SERIAL] == "ANON-SN-0002"


def test_the_megaraid_degraded_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Result 2 of M6: a degraded drive behind the controller produces a
    # notification that names controller and device ID, for a SATA drive
    # and for the derived SAS drive.
    host = megaraid_host(tmp_path, monkeypatch, "megaraid-degraded")

    assert only(host.run("01-healthy")).event is EventType.FIRST_RUN
    sata, sas = host.run("02-degraded")

    assert sata.subject == (
        "[pve-smart-alert] WARNING pve1: /dev/bus/6 ST6000NM0115-1YZ110 (ANON-SN-0001):"
        " 3 pending sectors"
    )
    assert "Drive:      /dev/bus/6 [sat+megaraid,14]\n" in sata.body
    assert "Location:   /dev/bus/6 (megaraid_sas), device 14\n" in sata.body
    assert sas.subject == (
        "[pve-smart-alert] WARNING pve1: /dev/bus/6 SEAGATE ST600MP0036 (ANON-SN-0002):"
        " 150 grown defects"
    )
    assert "Drive:      /dev/bus/6 [megaraid,8]\n" in sas.body
    assert "Location:   /dev/bus/6 (megaraid_sas), device 8\n" in sas.body
    assert sata.fields_for()[FIELD_DEVICE] == sas.fields_for()[FIELD_DEVICE] == "/dev/bus/6"
    # The device ID tells the two apart (ADR 0029).
    assert sata.fields_for()[FIELD_DEVICE_ID] == "14"
    assert sas.fields_for()[FIELD_DEVICE_ID] == "8"


def test_the_steps_can_be_built_for_a_real_host(tmp_path: Path) -> None:
    # The acceptance on a real host replays the same steps (ROADMAP.md, M4).
    assert main(["build", "pending-sectors", str(tmp_path / "scenario")]) == 0

    built = sorted(path.name for path in (tmp_path / "scenario").iterdir())
    assert built == [step.name for step in SCENARIOS["pending-sectors"].steps]
    assert (tmp_path / "scenario" / "01-healthy" / "recording.json").is_file()


def test_the_scenarios_can_be_listed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "pending-sectors" in out
    assert "09-gone" in out


def test_the_clock_moves_only_when_the_test_moves_it() -> None:
    clock = Clock()

    assert clock() == START
    assert clock.advance() == START + RUN_INTERVAL
    assert clock.advance(timedelta(days=7)) == START + RUN_INTERVAL + timedelta(days=7)


def test_the_recording_transport_keeps_or_refuses() -> None:
    transport = RecordingTransport()
    notification = Notification(
        event=EventType.TEST, severity=Severity.INFO, node="pve1", subject="s", body="b"
    )

    assert transport.send(notification).delivered
    assert transport.take() == [notification]
    assert transport.take() == []

    transport.failing = True
    assert not transport.send(notification).delivered
    assert transport.take() == []
