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
from hosts import FAKE, Host

from pve_smart_alert import cli
from pve_smart_alert import config as config_module
from pve_smart_alert.config import Config, DriveOverride, ManualDevice, TransportName
from pve_smart_alert.discovery import Discovery, discover
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
    fake smartctl and lsblk at one of them. The SCSI hosts and SCSI generic
    nodes of the scenario are written into the sysfs of the host, and its
    manual entries are part of every configuration.
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
        self.exit_status: int | None = None
        self.scsi_hosts(self.scenario.scsi_hosts)
        self.sg_nodes(self.scenario.sg_nodes)
        self.step(paths[0].name)

    def step(self, name: str) -> None:
        """Make the host look like one step of the scenario."""
        self.recording = self.steps[name]
        self._monkeypatch.setenv("FAKE_SMARTCTL_RECORDING", str(self.recording))

    def config(self, *, drives: tuple[DriveOverride, ...] = (), **discovery: object) -> Config:
        """The configuration of the host, with the manual entries of the scenario."""
        manual = tuple(ManualDevice(name, kind) for name, kind in self.scenario.devices)
        discovery.setdefault("devices", manual)
        return super().config(drives=drives, **discovery)

    def install(self, config: str = "") -> None:
        """Point the command-line interface at this host, and write its configuration.

        The configuration reads the drives with the fake smartctl; `config`
        is added to it. The notify bridge is a script that loads nothing and
        answers that it works, so that the transport counts as healthy.
        """
        patch = self._monkeypatch
        root = self.state_dir.parent
        self.config_path = root / "config.toml"
        manual = "".join(
            f'[[discovery.device]]\nname = "{name}"\ntype = "{kind}"\n'
            for name, kind in self.scenario.devices
        )
        self.config_path.write_text(
            f'[smartctl]\npath = "{FAKE}"\n{config}{manual}', encoding="utf-8"
        )
        self.state_path = self.state_dir / "state.json"
        bridge = root / "notify-bridge"
        bridge.write_text("#!/bin/sh\necho '{\"ok\": true}'\n", encoding="utf-8")
        bridge.chmod(0o755)
        patch.setattr(config_module, "CONFIG_PATH", self.config_path)
        patch.setattr(cli, "CONFIG_PATH", self.config_path)
        patch.setattr(cli, "LAST_GOOD_CONFIG_PATH", self.state_dir / "last-good-config.json")
        patch.setattr(cli, "STATE_PATH", self.state_path)
        self.lock_path = root / "run" / "lock"
        patch.setattr(cli, "LOCK_PATH", self.lock_path)
        patch.setattr(cli, "BRIDGE_PATH", bridge)
        patch.setattr(cli, "COROSYNC_CONF_PATH", root / "corosync.conf")
        patch.setattr(cli, "HOST_PATHS", self.paths)
        patch.setattr(cli, "clock", self.clock)
        patch.setattr(cli, "node_name", lambda: "pve1")
        patch.setattr(cli, "build_transport", lambda _settings: self.transport)
        patch.setattr(cli, "_reading", lambda _candidate: None)

        host = self

        def discover_on_host(config: Config, **kwargs: object) -> Discovery:
            kwargs.update(runner=host, paths=host.paths)
            return discover(config, **kwargs)  # type: ignore[arg-type]

        patch.setattr(cli, "discover", discover_on_host)

    def run(
        self, step: str | None = None, *, advance: timedelta = RUN_INTERVAL
    ) -> list[Notification]:
        """Run `pve-smart-alert check` once, a timer interval later, and return what it sent."""
        if step is not None:
            self.step(step)
        self.clock.advance(advance)
        self.exit_status = cli.main(["check"])
        return self.transport.take()
