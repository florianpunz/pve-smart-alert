# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the HPE Smart Array probe (FR-103, ADR 0032).

No host with such a controller was ever recorded (Research 08), so the probe
runs on a synthetic recording: the outputs of two drives of the maintainer's
TrueNAS host, with the device fields of a `cciss,N` read, and a device scan
that lists nothing. A device ID the recording does not have is an empty bay,
which the fake smartctl answers as smartctl does (tests/unit/hosts.py).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest
from frame import RUN_INTERVAL, Clock, RecordingTransport
from hosts import FAKE, HPE_NODE, Host, write_hpe_recording, write_scsi_hosts, write_sg_nodes

from pve_smart_alert import cli
from pve_smart_alert import config as config_module
from pve_smart_alert.collect import Status
from pve_smart_alert.config import Config, ManualDevice, SmartctlSettings
from pve_smart_alert.discovery import Discovery, Outcome, SkipReason, Source, discover
from pve_smart_alert.discovery.controllers import read_scsi_hosts
from pve_smart_alert.discovery.enrichment import HostPaths, scsi_host_of_sg, sg_node_of_host
from pve_smart_alert.discovery.probes import (
    CONSECUTIVE_FAILURES,
    MAX_DEVICE_ID,
    NAMED_DRIVERS,
    PROBED_DRIVER,
    HpeController,
    NotProbed,
    Probing,
    hpe_controllers,
    probe_hpe,
)
from pve_smart_alert.model import EventType, Notification, Snapshot
from pve_smart_alert.process import ProcessResult
from pve_smart_alert.scan_report import render
from pve_smart_alert.state import read_state

# A document the probe only has to judge as usable; the parsers are not asked.
_USABLE: Final = json.dumps(
    {
        "json_format_version": [1, 0],
        "device": {"name": "/dev/sg1", "type": "cciss", "protocol": "SCSI"},
        "smartctl": {"version": [7, 5], "argv": []},
    }
)

# What smartctl answers for a drive in standby behind the controller: no data,
# the exit status of `-n standby` and the message that names the power mode.
_STANDBY: Final = json.dumps(
    {
        "json_format_version": [1, 0],
        "smartctl": {
            "version": [7, 5],
            "argv": [],
            "messages": [
                {"string": "Device is in STANDBY mode, exit(2)", "severity": "information"}
            ],
            "exit_status": 2,
        },
    }
)


class Answers:
    """A runner that answers smartctl for the device IDs a test names."""

    def __init__(self, present: set[int], *, standby: set[int] | None = None) -> None:
        self.present = present
        self.standby = standby or set()
        self.calls: list[list[str]] = []

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,  # noqa: ARG002
        timeout: float,  # noqa: ARG002
    ) -> ProcessResult:
        self.calls.append([str(part) for part in command])
        device_type = next(str(part) for part in command if str(part).startswith("--device="))
        device_id = int(device_type.removeprefix("--device=cciss,"))
        if device_id in self.standby:
            return ProcessResult(returncode=2, stdout=_STANDBY, stderr="", timed_out=False)
        if device_id in self.present:
            return ProcessResult(returncode=0, stdout=_USABLE, stderr="", timed_out=False)
        return ProcessResult(returncode=2, stdout="", stderr="", timed_out=False)

    @property
    def types(self) -> list[str]:
        return [
            next(part.removeprefix("--device=") for part in call if part.startswith("--device="))
            for call in self.calls
        ]


def paths_with(
    tmp_path: Path, *, hosts: dict[int, str], nodes: dict[int, int] | None = None
) -> HostPaths:
    sysfs = tmp_path / "sys"
    write_scsi_hosts(sysfs, hosts)
    write_sg_nodes(sysfs, {} if nodes is None else nodes)
    return HostPaths(sysfs=sysfs)


def probed(
    tmp_path: Path, drivers: dict[int, str], *, probe_cciss: bool = True
) -> tuple[HpeController, ...]:
    paths = paths_with(tmp_path, hosts=drivers, nodes={1: 1})
    return hpe_controllers(read_scsi_hosts(paths).hosts, probe_cciss=probe_cciss, paths=paths)


def probe_with(
    tmp_path: Path,
    present: set[int],
    *,
    standby: set[int] | None = None,
    probe_cciss: bool = True,
) -> tuple[Answers, Probing]:
    paths = paths_with(tmp_path, hosts={1: "hpsa"}, nodes={1: 1})
    runner = Answers(present, standby=standby)
    probing = probe_hpe(
        read_scsi_hosts(paths).hosts,
        probe_cciss=probe_cciss,
        smartctl=SmartctlSettings(),
        paths=paths,
        runner=runner,
    )
    return runner, probing


# The constants of the probe


def test_the_probe_knows_the_driver_whose_hosts_smartctl_supports() -> None:
    # smartctl asks for -d cciss,N on hosts with the driver hpsa only
    # (os_linux.cpp, get_scsi_device, 7.5 lines 3363 to 3414 and 3475 to 3477).
    assert PROBED_DRIVER == "hpsa"
    assert {"smartpqi"} == NAMED_DRIVERS
    # smartctl accepts 0 <= N <= 127 (os_linux.cpp, 7.5 line 3583).
    assert (MAX_DEVICE_ID, CONSECUTIVE_FAILURES) == (127, 3)


# Where the probe reads


def test_the_host_of_a_node_is_read_from_the_scsi_device_name(tmp_path: Path) -> None:
    # The kernel names a SCSI device H:C:T:L; smartctl cuts the name at the
    # first colon to find the host (os_linux.cpp, is_hpsa_in_raid_mode).
    paths = paths_with(tmp_path, hosts={0: "ahci", 2: "hpsa"}, nodes={1: 0, 7: 2})

    assert scsi_host_of_sg(7, paths) == 2
    assert sg_node_of_host(2, paths) == "/dev/sg7"


def test_the_lowest_node_of_a_host_wins(tmp_path: Path) -> None:
    # A controller has one node per logical volume; any of them reaches it, and
    # the lowest number keeps the choice stable over runs.
    paths = paths_with(tmp_path, hosts={2: "hpsa"}, nodes={10: 2, 2: 2, 1: 0})

    assert sg_node_of_host(2, paths) == "/dev/sg2"


def test_a_node_without_a_link_and_a_host_without_a_node(tmp_path: Path) -> None:
    sysfs = tmp_path / "sys"
    (sysfs / "class" / "scsi_generic" / "sg3").mkdir(parents=True)
    write_scsi_hosts(sysfs, {2: "hpsa"})

    assert scsi_host_of_sg(3, HostPaths(sysfs=sysfs)) is None
    assert sg_node_of_host(2, HostPaths(sysfs=sysfs)) is None


def test_without_the_class_directory_there_is_no_node(tmp_path: Path) -> None:
    assert sg_node_of_host(2, HostPaths(sysfs=tmp_path / "sys")) is None


# Which controllers are probed


def test_only_a_host_with_hpsa_is_probed(tmp_path: Path) -> None:
    controllers = probed(
        tmp_path, {0: "ahci", 1: "hpsa", 2: "smartpqi", 3: "mpt3sas", 4: "aacraid"}
    )

    assert controllers == (
        HpeController(1, "hpsa", node="/dev/sg1"),
        HpeController(2, "smartpqi", reason=NotProbed.DRIVER),
    )


def test_the_probe_can_be_switched_off(tmp_path: Path) -> None:
    controllers = probed(tmp_path, {1: "hpsa"}, probe_cciss=False)

    assert controllers == (HpeController(1, "hpsa", reason=NotProbed.SWITCHED_OFF),)


def test_an_hpsa_host_without_a_node_is_not_probed(tmp_path: Path) -> None:
    paths = paths_with(tmp_path, hosts={1: "hpsa"})

    controllers = hpe_controllers(read_scsi_hosts(paths).hosts, probe_cciss=True, paths=paths)

    assert controllers == (HpeController(1, "hpsa", reason=NotProbed.NO_NODE),)


def test_a_smartpqi_host_keeps_its_reason_when_the_probe_is_off(tmp_path: Path) -> None:
    # Switching the probe on would not help: the driver is the reason.
    controllers = probed(tmp_path, {1: "smartpqi"}, probe_cciss=False)

    assert controllers == (HpeController(1, "smartpqi", reason=NotProbed.DRIVER),)


def test_every_controller_says_what_it_is() -> None:
    assert HpeController(2, "hpsa", node="/dev/sg1").describe() == (
        "SCSI host 2 has the driver hpsa and is probed as cciss,N on /dev/sg1"
    )
    assert HpeController(2, "hpsa", reason=NotProbed.SWITCHED_OFF).describe() == (
        "SCSI host 2 has the driver hpsa and is not probed:"
        " the probe is switched off with probe_cciss = false"
    )
    assert HpeController(2, "smartpqi", reason=NotProbed.DRIVER).describe() == (
        "SCSI host 2 has the driver smartpqi and is not probed: smartctl supports"
        " -d cciss,N only for the driver hpsa (ADR 0032); its drives can be added as"
        " [[discovery.device]]"
    )
    assert HpeController(2, "hpsa", reason=NotProbed.NO_NODE).describe() == (
        "SCSI host 2 has the driver hpsa and is not probed:"
        " no SCSI generic node (/dev/sgN) of this host was found"
    )


# What the probe reads


def test_the_probe_reads_from_zero_and_stops_after_three_failures(tmp_path: Path) -> None:
    runner, probing = probe_with(tmp_path, {0, 1})

    assert probing.controllers[0].device_ids == (0, 1)
    assert [candidate.type for candidate, _ in probing.readings] == ["cciss,0", "cciss,1"]
    # 0 and 1 answered; 2, 3 and 4 answered nothing, which ends the probe.
    assert runner.types == ["cciss,0", "cciss,1", "cciss,2", "cciss,3", "cciss,4"]


def test_a_bay_that_answers_nothing_does_not_end_the_probe(tmp_path: Path) -> None:
    runner, probing = probe_with(tmp_path, {0, 2})

    assert probing.controllers[0].device_ids == (0, 2)
    assert runner.types == ["cciss,0", "cciss,1", "cciss,2", "cciss,3", "cciss,4", "cciss,5"]


def test_three_standby_answers_in_a_row_are_not_failures(tmp_path: Path) -> None:
    # A sleeping drive is not an empty bay: every standby answer is kept as a
    # reading, it does not count as a failure, and the probe reads on (FR-203).
    runner, probing = probe_with(tmp_path, {3}, standby={0, 1, 2})

    assert probing.controllers[0].device_ids == (0, 1, 2, 3)
    assert [collected.status for _candidate, collected in probing.readings] == [
        Status.STANDBY,
        Status.STANDBY,
        Status.STANDBY,
        Status.OK,
    ]
    # 4, 5 and 6 answer nothing, which ends the probe.
    assert runner.types == [
        "cciss,0",
        "cciss,1",
        "cciss,2",
        "cciss,3",
        "cciss,4",
        "cciss,5",
        "cciss,6",
    ]


def test_the_probe_stops_at_the_highest_device_id_smartctl_accepts(tmp_path: Path) -> None:
    runner, probing = probe_with(tmp_path, set(range(MAX_DEVICE_ID + 1)))

    assert probing.controllers[0].device_ids[-1] == MAX_DEVICE_ID
    assert len(runner.types) == MAX_DEVICE_ID + 1


def test_a_switched_off_probe_reads_nothing(tmp_path: Path) -> None:
    runner, probing = probe_with(tmp_path, {0}, probe_cciss=False)

    assert probing.readings == ()
    assert runner.calls == []


def test_the_probe_hands_on_what_it_read(tmp_path: Path) -> None:
    _runner, probing = probe_with(tmp_path, {0})

    (candidate, collected) = probing.readings[0]
    assert (candidate.name, candidate.type, candidate.source) == (
        HPE_NODE,
        "cciss,0",
        Source.PROBE,
    )
    assert collected.status is Status.OK


def test_the_probe_does_not_wake_a_sleeping_drive(tmp_path: Path) -> None:
    # The probe passes --nocheck=standby like every other read: a drive behind
    # the controller can be a SATA or a SAS drive, and smartctl checks the
    # power mode for both (FR-203, ADR 0032).
    runner, _probing = probe_with(tmp_path, {0})

    assert runner.calls[0][-5:] == [
        "--json=c",
        "--xall",
        "--device=cciss,0",
        "--nocheck=standby",
        HPE_NODE,
    ]


# The probe in a run of discovery


def hpe_recording(tmp_path: Path) -> Path:
    """Write the synthetic recording of an HPE host and return its directory."""
    recording = tmp_path / "hpe"
    write_hpe_recording(recording)
    return recording


def hpe_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    """A host with an HPE Smart Array controller behind hpsa (ADR 0032)."""
    host = Host(tmp_path, monkeypatch, hpe_recording(tmp_path))
    host.scsi_hosts({0: "ahci", 1: "hpsa"})
    host.sg_nodes({1: 1})
    return host


def read_types(host: Host) -> list[str]:
    """Return the types smartctl was asked for, the scans left out."""
    calls = [json.loads(line) for line in host.log.read_text(encoding="utf-8").splitlines()]
    return [
        next(part.removeprefix("--device=") for part in call if part.startswith("--device="))
        for call in calls
        if "--scan-open" not in call and "--scan" not in call
    ]


def snapshots(discovery: Discovery) -> list[Snapshot]:
    """Return the snapshots of the drives the run monitors, in the order found."""
    result = []
    for found in discovery.devices:
        if found.outcome is not Outcome.MONITORED:
            continue
        assert found.snapshot is not None
        result.append(found.snapshot)
    return result


def test_the_probe_finds_the_drives_behind_the_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hpe_host(tmp_path, monkeypatch)

    discovery = host.discover()

    monitored = [found for found in discovery.devices if found.outcome is Outcome.MONITORED]
    assert [found.candidate.type for found in monitored] == ["cciss,0", "cciss,1"]
    assert {found.candidate.source for found in monitored} == {Source.PROBE}
    assert discovery.probe.controllers[0].device_ids == (0, 1)
    # A SATA drive and a SAS drive, read through the same node. The protocol of
    # a probed drive comes from its output, because the probe has no scan entry
    # that names it (ADR 0032).
    assert [snapshot.access.protocol for snapshot in snapshots(discovery)] == ["ATA", "SCSI"]


def test_a_sleeping_drive_keeps_the_probe_going(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A drive in standby answers without data and is handed on like a drive
    # that was read: discovery keeps its previous state (FR-203), and its answer
    # proves that the device ID exists, so the probe reads on (ADR 0032).
    host = hpe_host(tmp_path, monkeypatch)
    host.behave("cciss0.json", standby="STANDBY")

    discovery = host.discover()

    outcomes = {found.candidate.type: found.outcome for found in discovery.devices}
    assert outcomes == {"cciss,0": Outcome.STANDBY, "cciss,1": Outcome.MONITORED}
    assert read_types(host) == ["cciss,0", "cciss,1", "cciss,2", "cciss,3", "cciss,4"]


def test_the_location_is_the_controller_and_the_device_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hpe_host(tmp_path, monkeypatch)

    first, second = snapshots(host.discover())

    assert first.location.controller == f"{HPE_NODE} (hpsa)"
    assert first.location.device_id == "0"
    assert second.location.controller_text == f"{HPE_NODE} (hpsa), device 1"


def test_an_empty_bay_is_no_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = hpe_host(tmp_path, monkeypatch)

    discovery = host.discover()

    assert read_types(host) == ["cciss,0", "cciss,1", "cciss,2", "cciss,3", "cciss,4"]
    assert [found.candidate.type for found in discovery.devices] == ["cciss,0", "cciss,1"]


def test_a_drive_the_scan_lists_is_kept_over_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An HPE controller in HBA mode: the drive appears in the scan and behind
    # the controller. It is monitored once, through the scan (FR-106).
    host = hpe_host(tmp_path, monkeypatch)
    document = json.loads((host.recording / "cciss0.json").read_text(encoding="utf-8"))
    document["device"].update({"name": "/dev/sda", "type": "sat", "info_name": "/dev/sda [SAT]"})
    document["smartctl"]["argv"] = ["smartctl", "-x", "--json=c", "-d", "sat", "/dev/sda"]
    host.add_file("sda.json", document, device="/dev/sda", device_type="sat")
    scan = host.drive("scan.json")
    scan["devices"] = [
        {"name": "/dev/sda", "info_name": "/dev/sda [SAT]", "type": "sat", "protocol": "ATA"}
    ]
    (host.recording / "scan.json").write_text(json.dumps(scan), encoding="utf-8")

    discovery = host.discover()

    # The devices of the scan are read first, then those of the probe
    # (ARCHITECTURE.md section 5): the drive that is found twice is read twice
    # in this run and kept once, through the scan.
    assert read_types(host) == ["sat", "cciss,0", "cciss,1", "cciss,2", "cciss,3", "cciss,4"]
    monitored = [found for found in discovery.devices if found.outcome is Outcome.MONITORED]
    assert [found.candidate.name for found in monitored] == ["/dev/sda", HPE_NODE]
    duplicate = [found for found in discovery.devices if found.reason is SkipReason.DUPLICATE]
    assert [found.candidate.type for found in duplicate] == ["cciss,0"]
    assert duplicate[0].detail == "the same drive as /dev/sda"
    assert snapshots(discovery)[0].access.aliases == (HPE_NODE,)


def test_a_manual_entry_of_a_probed_device_is_not_read_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hpe_host(tmp_path, monkeypatch)
    config = host.config(devices=(ManualDevice(HPE_NODE, "cciss,0"),))

    discovery = discover(config, runner=host, paths=host.paths)

    assert read_types(host) == ["cciss,0", "cciss,1", "cciss,2", "cciss,3", "cciss,4"]
    manual = [found for found in discovery.devices if found.candidate.source is Source.MANUAL]
    assert [(found.candidate.type, found.reason) for found in manual] == [
        ("cciss,0", SkipReason.DUPLICATE)
    ]


def test_the_configuration_switches_the_probe_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hpe_host(tmp_path, monkeypatch)

    discovery = host.discover(probe_cciss=False)

    assert read_types(host) == []
    assert discovery.devices == ()
    assert discovery.probe.controllers[0].reason is NotProbed.SWITCHED_OFF


# What `scan` says about the controllers (FR-108, FR-109)


def scan_text(discovery: Discovery) -> str:
    return "\n".join(render(discovery, smartctl_path=Path("/usr/sbin/smartctl")))


def test_scan_names_the_controller_and_what_it_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hpe_host(tmp_path, monkeypatch)

    text = scan_text(host.discover())

    assert (
        "HPE Smart Array: SCSI host 1 has the driver hpsa and is probed as cciss,N on"
        " /dev/sg1: 2 drives found (cciss,0, cciss,1)" in text
    )
    assert f"{HPE_NODE} [cciss,0], from the probe: monitored" in text


def test_scan_names_a_smartpqi_controller_that_is_not_probed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hpe_host(tmp_path, monkeypatch)
    host.scsi_hosts({0: "ahci", 1: "smartpqi"})

    text = scan_text(host.discover())

    assert "HPE Smart Array: SCSI host 1 has the driver smartpqi and is not probed" in text
    assert "its drives can be added as [[discovery.device]]" in text
    assert "from the probe" not in text


def test_scan_says_when_the_probe_is_switched_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hpe_host(tmp_path, monkeypatch)

    text = scan_text(host.discover(probe_cciss=False))

    assert "is not probed: the probe is switched off with probe_cciss = false" in text


# A run of `check` with the probe switched between runs


class CheckHost(Host):
    """A host the command line runs `check` against, with a state of its own.

    The scenario frame does the same for a scenario (`tests/unit/frame.py`);
    this one is for the synthetic HPE recording, where the configuration is
    switched between runs.
    """

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path) -> None:
        super().__init__(tmp_path, monkeypatch, source)
        self.root = tmp_path
        self.state_path = tmp_path / "state" / "state.json"
        self.config_path = tmp_path / "config.toml"
        self.clock = Clock()
        self.transport = RecordingTransport()
        self.monkeypatch = monkeypatch

    def write_config(self, extra: str = "") -> None:
        """Write the configuration the command line reads."""
        self.config_path.write_text(f'[smartctl]\npath = "{FAKE}"\n{extra}', encoding="utf-8")

    def install(self) -> None:
        """Point the command line at this host, its state and a recording transport."""
        patch = self.monkeypatch
        self.write_config()
        bridge = self.root / "notify-bridge"
        bridge.write_text("#!/bin/sh\necho '{\"ok\": true}'\n", encoding="utf-8")
        bridge.chmod(0o755)
        patch.setattr(config_module, "CONFIG_PATH", self.config_path)
        patch.setattr(cli, "CONFIG_PATH", self.config_path)
        patch.setattr(cli, "LAST_GOOD_CONFIG_PATH", self.root / "state" / "last-good-config.json")
        patch.setattr(cli, "STATE_PATH", self.state_path)
        patch.setattr(cli, "LOCK_PATH", self.root / "run" / "lock")
        patch.setattr(cli, "BRIDGE_PATH", bridge)
        patch.setattr(cli, "COROSYNC_CONF_PATH", self.root / "corosync.conf")
        patch.setattr(cli, "HOST_PATHS", self.paths)
        patch.setattr(cli, "clock", self.clock)
        patch.setattr(cli, "node_name", lambda: "hpe1")
        patch.setattr(cli, "build_transport", lambda _settings: self.transport)
        patch.setattr(cli, "_reading", lambda _candidate: None)
        host = self

        def discover_on_host(config: Config, **kwargs: object) -> Discovery:
            kwargs.update(runner=host, paths=host.paths)
            return discover(config, **kwargs)  # type: ignore[arg-type]

        patch.setattr(cli, "discover", discover_on_host)

    def run(self) -> list[Notification]:
        """Run `check` once, a timer interval later, and return what it sent."""
        self.clock.advance(RUN_INTERVAL)
        cli.main(["check"])
        return self.transport.take()


def check_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CheckHost:
    host = CheckHost(tmp_path, monkeypatch, hpe_recording(tmp_path))
    host.scsi_hosts({0: "ahci", 1: "hpsa"})
    host.sg_nodes({1: 1})
    host.install()
    return host


def test_switching_the_probe_off_forgets_its_drives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = check_host(tmp_path, monkeypatch)

    (first,) = host.run()
    assert first.event is EventType.FIRST_RUN

    # The probe is switched off: the drives that only it can find are forgotten
    # silently, not reported as missing, however many runs pass (ADR 0032).
    host.write_config("[discovery]\nprobe_cciss = false\n")
    assert host.run() == []
    assert host.run() == []
    state, error = read_state(host.state_path, now=host.clock())
    assert error is None
    assert state is not None
    assert state.drives == {}

    # Switched on again they are new records: no recovery, no summary.
    host.write_config()
    assert host.run() == []
    state, error = read_state(host.state_path, now=host.clock())
    assert error is None
    assert state is not None
    assert len(state.drives) == 2


def test_a_manual_entry_is_read_while_the_probe_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A manual entry does not depend on the probe: the drive it names is read,
    # and only the drives that the probe alone can find stay unseen (ADR 0032).
    host = check_host(tmp_path, monkeypatch)
    host.write_config(
        "[discovery]\nprobe_cciss = false\n"
        '[[discovery.device]]\nname = "/dev/sg1"\ntype = "cciss,0"\n'
    )

    (first,) = host.run()

    assert first.event is EventType.FIRST_RUN
    state, error = read_state(host.state_path, now=host.clock())
    assert error is None
    assert state is not None
    assert len(state.drives) == 1
