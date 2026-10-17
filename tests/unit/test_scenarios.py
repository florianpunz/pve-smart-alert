# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the scenario frame (ADR 0016).

The steps of every scenario are recordings the fake smartctl replays, and
each step shows the host the scenario says it shows. The clock and the
recording transport of the frame do what the scenario tests rely on.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from frame import RUN_INTERVAL, START, Clock, RecordingTransport, ScenarioHost

from pve_smart_alert.checks import evaluate
from pve_smart_alert.discovery import Outcome, SkipReason, Source
from pve_smart_alert.discovery.enrichment import details_of, read_block_devices
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


def only(notifications: list[Notification]) -> Notification:
    assert len(notifications) == 1, [n.subject for n in notifications]
    return notifications[0]


def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> ScenarioHost:
    host = ScenarioHost(tmp_path, monkeypatch, name)
    host.install()
    return host


# One scenario per controller family (ROADMAP.md, M6, result 1). The table
# of docs/hardware-support.md names the scenario of each family.


def test_the_onboard_sata_nvme_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Drives on the board are read directly: no controller, no device ID.
    host = installed(tmp_path, monkeypatch, "onboard-sata-nvme")

    first = only(host.run("01-healthy"))
    assert first.subject == "[pve-smart-alert] INFO pve1: monitoring 3 drives, no findings"
    warning = only(host.run("02-media-errors"))
    assert warning.event is EventType.PROBLEM
    assert warning.subject == (
        "[pve-smart-alert] WARNING pve1: /dev/nvme0 SAMSUNG MZVLW256HEHP-000L2 (ANON-SN-0002):"
        " 2 media errors"
    )
    assert "Drive:      /dev/nvme0 [nvme]\n" in warning.body
    assert warning.fields_for()[FIELD_DEVICE] == "/dev/nvme0"
    assert FIELD_DEVICE_ID not in warning.fields_for()


def test_the_hba_sas_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Result 3 of M6 on the recording of the TrueNAS host: the SAS SSDs behind
    # the mpt2sas HBA are block devices of the host, and neither mpt2sas nor
    # ahciem is reported as a controller that cannot be queried (ADR 0030).
    host = installed(tmp_path, monkeypatch, "hba-sas")

    devices = host.discover().devices
    assert [(found.candidate.name, found.candidate.type) for found in devices] == [
        ("/dev/sda", "scsi"),
        ("/dev/sdc", "scsi"),
        ("/dev/sdd", "sat"),
        ("/dev/sde", "scsi"),
    ]
    assert all(found.outcome is Outcome.MONITORED for found in devices)
    first = only(host.run("01-healthy"))
    assert first.subject == "[pve-smart-alert] INFO pve1: monitoring 4 drives, no findings"
    assert "tool.unsupported_controller" not in first.body

    warning = only(host.run("02-grown-defects"))
    assert warning.subject == (
        "[pve-smart-alert] WARNING pve1: /dev/sdc NETAPP X371_SLBPE960ATE (ANON-SN-0002):"
        " 150 grown defects"
    )
    assert "Drive:      /dev/sdc [scsi]\n" in warning.body
    assert FIELD_DEVICE_ID not in warning.fields_for()


def test_the_hpe_smart_array_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Synthetic and experimental (ADR 0032): the probe finds both drives
    # behind hpsa, and a finding names the controller and the device ID.
    host = installed(tmp_path, monkeypatch, "hpe-smart-array")

    monitored = [
        (found.candidate.name, found.candidate.type) for found in host.discover().monitored
    ]
    assert monitored == [("/dev/sg1", "cciss,0"), ("/dev/sg1", "cciss,1")]
    first = only(host.run("01-healthy"))
    assert first.subject == "[pve-smart-alert] INFO pve1: monitoring 2 drives, no findings"

    warning = only(host.run("02-pending-3"))
    assert warning.subject == (
        "[pve-smart-alert] WARNING pve1: /dev/sg1 Samsung SSD 850 EVO 120GB (ANON-SN-0003):"
        " 3 pending sectors"
    )
    assert "Drive:      /dev/sg1 [cciss,0]\n" in warning.body
    assert "Location:   /dev/sg1 (hpsa), device 0\n" in warning.body
    assert warning.fields_for()[FIELD_DEVICE_ID] == "0"


def test_the_unsupported_mpi3mr_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Synthetic: the drives behind mpi3mr cannot be read, and the first run
    # says so; the on-board drive is monitored (ADR 0030, ADR 0031).
    host = installed(tmp_path, monkeypatch, "unsupported-mpi3mr")

    first = only(host.run("01-first"))
    assert first.subject == "[pve-smart-alert] NOTICE pve1: monitoring 1 drive, no findings"
    assert "tool.unsupported_controller: SCSI host 2 has the driver mpi3mr" in first.body
    assert "1 drive is monitored on this host" in first.body
    assert host.run("02-again") == []


def test_the_manual_pass_through_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Derived: a drive behind each controller other than MegaRAID and cciss is
    # read with its type on its node; the scan lists the SSSRAID drive, manual
    # entries name the others (FR-104, ADR 0034). What the host shows for a
    # node such as the logical volume /dev/sdc, with its ZFS pool, is not the
    # drive's (ADR 0028), and these types have no device ID.
    host = installed(tmp_path, monkeypatch, "manual-pass-through")
    volume = details_of("/dev/sdc", read_block_devices(host.paths, runner=host), host.paths)
    assert volume.membership.zfs_pool == "tank"

    devices = host.discover().devices
    assert [(found.candidate.name, found.candidate.type) for found in devices] == [
        ("/dev/sda", "sat"),
        ("/dev/bsg/sssraid0", "sssraid,0,1"),
        ("/dev/sg2", "areca,2"),
        ("/dev/sg3", "areca,1/1"),
        ("/dev/twa0", "3ware,1"),
        ("/dev/sdc", "aacraid,0,0,2"),
        ("/dev/sdd", "hpt,1/2/3"),
    ]
    assert devices[1].candidate.source is Source.SCAN
    assert all(found.candidate.source is Source.MANUAL for found in devices[2:])
    assert all(found.outcome is Outcome.MONITORED for found in devices)
    for found in devices[1:]:
        assert found.details.block_device is False
        assert found.details.membership.zfs_pool is None
        assert found.details.location.controller_text is None
    # None of them is woken in standby (FR-203).
    log = [json.loads(line) for line in host.log.read_text(encoding="utf-8").splitlines()]
    reads = [call for call in log if "--scan-open" not in call and call[-1] != "/dev/sda"]
    assert reads
    assert all("--nocheck=standby" in call for call in reads)

    first = only(host.run("01-healthy"))
    assert first.subject == "[pve-smart-alert] INFO pve1: monitoring 7 drives, no findings"
    assert "/dev/sdc [aacraid,0,0,2] NETAPP X371_SLBPE960ATE (ANON-SN-0005)  no findings" in (
        first.body
    )

    three_ware, adaptec = host.run("02-degraded")
    assert three_ware.subject == (
        "[pve-smart-alert] WARNING pve1: /dev/twa0 Fanxiang S301 256GB (ANON-SN-0004):"
        " 3 pending sectors"
    )
    assert "Drive:      /dev/twa0 [3ware,1]\n" in three_ware.body
    assert adaptec.subject == (
        "[pve-smart-alert] WARNING pve1: /dev/sdc NETAPP X371_SLBPE960ATE (ANON-SN-0005):"
        " 150 grown defects"
    )
    assert "Drive:      /dev/sdc [aacraid,0,0,2]\n" in adaptec.body
    assert "Location:" not in adaptec.body
    assert "tank" not in adaptec.body
    for notification in (three_ware, adaptec):
        assert FIELD_DEVICE_ID not in notification.fields_for()


def megaraid_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> ScenarioHost:
    """A MegaRAID scenario, installed; the scenario names SCSI host 6 of `megaraid_sas`."""
    host = ScenarioHost(tmp_path, monkeypatch, name)
    host.install()
    return host


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


# A state that the code of 0.5.0~dev2 wrote after the steps 01 to 04 of the
# scenario `megaraid-id-change` (tests/fixtures/SOURCES.md).
DEV2_STATE = Path(__file__).parents[1] / "fixtures" / "state" / "dev2-megaraid-id-change.json"


def test_a_state_of_an_earlier_build_is_read_and_continued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The schema is still 1, so nothing is migrated (ADR 0007). The device
    # type of the last read was kept since the first schema, so a drive that
    # goes missing from that state carries the device ID dev2 read (ADR 0029).
    host = megaraid_host(tmp_path, monkeypatch, "megaraid-id-change")
    host.state_dir.mkdir()
    shutil.copy(DEV2_STATE, host.state_path)
    host.clock.now = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)

    assert host.run("05-gone") == []
    missing = only(host.run("06-gone"))

    assert host.exit_status == 0
    assert not [path for path in host.state_dir.iterdir() if ".corrupt-" in path.name]
    assert missing.event is EventType.MISSING
    fields = missing.fields_for()
    assert fields[FIELD_DEVICE] == "/dev/bus/6"
    assert fields[FIELD_DEVICE_ID] == "9"
    assert fields[FIELD_SERIAL] == "ANON-SN-0002"
    state = json.loads(host.state_path.read_text(encoding="utf-8"))
    assert state["schema"] == 1
    sata = state["drives"]["ST6000NM0115-1YZ110|ANON-SN-0001"]
    assert sata["conditions"]["ata.pending_sectors"]["first_detected"] == "2026-10-12T09:00:00Z"


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
    assert "host2 mpi3mr in sysfs" in out


def test_a_real_host_is_told_what_the_frame_adds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # On a real host the steps alone do not make the scenario: the manual
    # entries go into the configuration, and sysfs is the host's own.
    assert main(["build", "manual-pass-through", str(tmp_path / "scenario")]) == 0

    entries = (tmp_path / "scenario" / "manual-entries.toml").read_text(encoding="utf-8")
    assert '[[discovery.device]]\nname = "/dev/twa0"\ntype = "3ware,1"\n' in entries
    assert "sssraid" not in entries
    assert "needs the manual entries of manual-entries.toml" in capsys.readouterr().err


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
