# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the scenario frame (ADR 0016).

The steps of every scenario are recordings the fake smartctl replays, and
each step shows the host the scenario says it shows. The clock and the
recording transport of the frame do what the scenario tests rely on.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from frame import RUN_INTERVAL, START, Clock, RecordingTransport, ScenarioHost

from pve_smart_alert.checks import evaluate
from pve_smart_alert.discovery import Outcome
from pve_smart_alert.model import EventType, Notification, Severity
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
