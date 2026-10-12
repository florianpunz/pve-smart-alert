# SPDX-License-Identifier: AGPL-3.0-or-later
"""The frame of the scenario tests (ADR 0016).

A scenario test runs the program once per step of a scenario of
`tests/scenarios.py`, against the fake smartctl, with a clock it sets
itself, a temporary state directory and a transport that records instead
of sending. Nothing here needs root, a Proxmox VE host or a real drive
(NFR-15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from hosts import Host

from pve_smart_alert.config import TransportName
from pve_smart_alert.model import Notification
from pve_smart_alert.transports import TransportOutcome
from scenarios import SCENARIOS, Scenario, build

#: Where every scenario starts: an arbitrary moment, in UTC.
START: Final = datetime(2026, 10, 12, 8, 0, 0, tzinfo=UTC)

#: The interval of the timer between two runs (ADR 0006).
RUN_INTERVAL: Final = timedelta(minutes=30)


@dataclass
class Clock:
    """A clock the test moves by hand. The program reads it instead of the system clock."""

    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta = RUN_INTERVAL) -> datetime:
        self.now += delta
        return self.now


@dataclass
class RecordingTransport:
    """A transport that keeps what it is given, and can be made to fail."""

    sent: list[Notification] = field(default_factory=list)
    failing: bool = False
    name: TransportName = TransportName.PVE_NOTIFY

    def send(self, notification: Notification) -> TransportOutcome:
        if self.failing:
            return TransportOutcome(
                delivered=False, transport=self.name, duration_seconds=0.0, error="made to fail"
            )
        self.sent.append(notification)
        return TransportOutcome(delivered=True, transport=self.name, duration_seconds=0.0)

    def take(self) -> list[Notification]:
        """Return what was sent since the last call, and forget it."""
        taken, self.sent = self.sent, []
        return taken


class ScenarioHost(Host):
    """A host whose recording is the current step of a scenario.

    The steps are built once into the temporary directory; `step` points the
    fake smartctl and lsblk at one of them.
    """

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
        self.scenario: Scenario = SCENARIOS[scenario]
        paths = build(self.scenario, tmp_path / "steps")
        self.steps = {path.name: path for path in paths}
        self._monkeypatch = monkeypatch
        super().__init__(tmp_path, monkeypatch, paths[0])
        self.state_dir = tmp_path / "state"
        self.clock = Clock()
        self.transport = RecordingTransport()
        self.step(paths[0].name)

    def step(self, name: str) -> None:
        """Make the host look like one step of the scenario."""
        self.recording = self.steps[name]
        self._monkeypatch.setenv("FAKE_SMARTCTL_RECORDING", str(self.recording))
