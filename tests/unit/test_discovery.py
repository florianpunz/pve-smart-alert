# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for discovery (ADR 0005).

The fake smartctl runs as a real program and replays the anonymized
recordings of the test cluster; lsblk is answered from the same recording
(ADR 0016). Changes to a recording for one case are made on a copy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hosts import Host

from pve_smart_alert.config import (
    Detail,
    DriveOverride,
    DriveSelector,
    ManualDevice,
    SelectorKind,
)
from pve_smart_alert.discovery import (
    Outcome,
    SkipReason,
    Source,
)
from pve_smart_alert.discovery.enrichment import parse_block_devices, volume_group_of
from pve_smart_alert.model import DriveClass


@pytest.fixture
def pve7(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host.of_node(tmp_path, monkeypatch, "pve7")


# The recordings of the test cluster


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ("pve5", [("/dev/sda", "Fanxiang S301 256GB", "ANON-SN-0001", DriveClass.SSD, "pve")]),
        (
            "pve6",
            [
                (
                    "/dev/sda",
                    "Samsung SSD 750 EVO 500GB",
                    "ANON-SN-0001",
                    DriveClass.SSD,
                    "vg_data",
                ),
                (
                    "/dev/nvme0",
                    "WDC PC SN720 SDAPNTW-512G-1016",
                    "ANON-SN-0002",
                    DriveClass.NVME,
                    "pve",
                ),
            ],
        ),
        (
            "pve7",
            [
                ("/dev/sda", "Samsung SSD 850 EVO 250GB", "ANON-SN-0001", DriveClass.SSD, "pve"),
                (
                    "/dev/nvme0",
                    "SAMSUNG MZVLW256HEHP-000L2",
                    "ANON-SN-0002",
                    DriveClass.NVME,
                    "pm961-b",
                ),
                (
                    "/dev/nvme1",
                    "SAMSUNG MZVLW256HEHP-000H1",
                    "ANON-SN-0003",
                    DriveClass.NVME,
                    "pm961-a",
                ),
            ],
        ),
    ],
)
def test_every_drive_of_a_node_is_found_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    node: str,
    expected: list[tuple[str, str, str, DriveClass, str]],
) -> None:
    # Acceptance step 1 of M2, on the recordings (Research 06).
    discovery = Host.of_node(tmp_path, monkeypatch, node).discover()

    seen = []
    for found in discovery.devices:
        assert found.outcome is Outcome.MONITORED
        assert found.candidate.source is Source.SCAN
        snapshot = found.snapshot
        assert snapshot is not None
        seen.append(
            (
                found.candidate.name,
                snapshot.identity.model,
                snapshot.identity.serial,
                snapshot.drive_class,
                snapshot.membership.volume_group,
            )
        )
    assert seen == expected
    assert discovery.smartctl_version == (7, 5)
    assert discovery.scan_error is None
    assert discovery.enrichment_error is None


@pytest.mark.parametrize("node", ["pve5", "pve6", "pve7"])
def test_the_pools_of_guests_are_not_the_pools_of_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, node: str
) -> None:
    # The disks of virtual machines on pve5 and pve7 hold a ZFS pool "zroot"
    # of the guest, which lsblk shows below the logical volume; the host uses
    # no ZFS (Research 06).
    for found in Host.of_node(tmp_path, monkeypatch, node).discover().devices:
        assert found.snapshot is not None
        assert found.snapshot.membership.zfs_pool is None
        assert found.snapshot.membership.md_array is None


def test_a_pool_on_a_partition_is_the_pool_of_the_host(pve7: Host) -> None:
    path = pve7.recording / "lsblk.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    partition = document["blockdevices"][0]["children"][0]
    partition.update(fstype="zfs_member", label="tank")
    partition["children"] = [{"name": "md127", "kname": "md127", "type": "raid1"}]
    path.write_text(json.dumps(document), encoding="utf-8")

    membership = pve7.discover().devices[0].details.membership

    assert membership.zfs_pool == "tank"
    assert membership.md_array == "md127"
    assert membership.volume_group == "pve"


def test_the_transport_comes_from_lsblk(pve7: Host) -> None:
    transports = [found.details.location.transport for found in pve7.discover().devices]

    assert transports == ["sata", "nvme", "nvme"]


def test_a_drive_only_lsblk_shows_is_not_monitored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The USB drive of the KVM-over-IP device on pve5 is not in the scan.
    discovery = Host.of_node(tmp_path, monkeypatch, "pve5").discover()

    assert [found.candidate.name for found in discovery.devices] == ["/dev/sda"]


# Manual devices (FR-104)


def test_a_manual_device_that_does_not_exist_is_unreadable(pve7: Host) -> None:
    # Acceptance step 4 of M2: the scan still completes.
    discovery = pve7.discover(devices=(ManualDevice("/dev/sdz", "sat"),))

    *scanned, manual = discovery.devices
    assert [found.outcome for found in scanned] == [Outcome.MONITORED] * 3
    assert manual.candidate.source is Source.MANUAL
    assert manual.outcome is Outcome.UNREADABLE
    assert manual.detail == "Smartctl open device: /dev/sdz failed: No such device"


def test_a_manual_device_the_scan_lists_as_well_is_read_once(pve7: Host) -> None:
    discovery = pve7.discover(devices=(ManualDevice("/dev/sda", "sat"),))

    manual = discovery.devices[-1]
    assert manual.outcome is Outcome.SKIPPED
    assert manual.reason is SkipReason.DUPLICATE
    assert pve7.read_devices().count("/dev/sda") == 1


def test_a_drive_reached_through_two_paths_is_kept_once(pve7: Host) -> None:
    # The same drive through a pass-through path (FR-106).
    pve7.add_file("sg0.json", pve7.drive("sda.json"), device="/dev/sg0", device_type="sat")

    discovery = pve7.discover(devices=(ManualDevice("/dev/sg0", "sat"),))

    kept, duplicate = discovery.devices[0], discovery.devices[-1]
    assert kept.outcome is Outcome.MONITORED
    assert kept.snapshot is not None
    assert kept.snapshot.access.aliases == ("/dev/sg0",)
    assert duplicate.outcome is Outcome.SKIPPED
    assert duplicate.reason is SkipReason.DUPLICATE
    assert duplicate.detail == "the same drive as /dev/sda"


def test_drives_without_a_stable_identity_are_not_merged(pve7: Host) -> None:
    anonymous = pve7.drive("sda.json")
    del anonymous["serial_number"]
    del anonymous["wwn"]
    pve7.add_file("first.json", anonymous, device="/dev/sg1", device_type="sat")
    pve7.add_file("second.json", anonymous, device="/dev/sg2", device_type="sat")

    discovery = pve7.discover(
        devices=(ManualDevice("/dev/sg1", "sat"), ManualDevice("/dev/sg2", "sat"))
    )

    assert [found.outcome for found in discovery.devices[-2:]] == [Outcome.MONITORED] * 2


# Filtering (FR-107)


def test_an_excluded_drive_is_skipped_with_its_rule(pve7: Host) -> None:
    rule = DriveSelector(SelectorKind.MODEL, "SAMSUNG MZVLW256HEHP-*")

    discovery = pve7.discover(exclude=(rule,))

    assert [found.outcome for found in discovery.devices] == [
        Outcome.MONITORED,
        Outcome.SKIPPED,
        Outcome.SKIPPED,
    ]
    assert discovery.devices[1].reason is SkipReason.EXCLUDED
    assert discovery.devices[1].detail == 'model = "SAMSUNG MZVLW256HEHP-*"'


def test_a_sleeping_drive_is_not_woken(pve7: Host) -> None:
    pve7.behave("sda.json", standby="STANDBY")

    found = pve7.discover().devices[0]

    assert found.outcome is Outcome.STANDBY
    assert found.detail == "STANDBY"


def test_a_drive_on_a_remote_transport_is_not_read(pve7: Host) -> None:
    pve7.change_lsblk("sda", tran="iscsi")

    found = pve7.discover().devices[0]

    assert found.outcome is Outcome.SKIPPED
    assert found.reason is SkipReason.REMOTE
    assert "/dev/sda" not in pve7.read_devices()


def test_nvme_over_fabrics_is_remote(pve7: Host) -> None:
    transport = pve7.paths.sysfs / "class" / "nvme" / "nvme1" / "transport"
    transport.parent.mkdir(parents=True)
    transport.write_text("tcp\n", encoding="utf-8")

    found = pve7.discover().devices[2]

    assert found.reason is SkipReason.REMOTE
    assert found.detail == "transport tcp"


def test_a_device_that_is_not_a_disk_is_not_read(pve7: Host) -> None:
    pve7.change_lsblk("sr0", type="rom")

    found = pve7.discover(devices=(ManualDevice("/dev/sr0", "scsi"),)).devices[-1]

    assert found.reason is SkipReason.NOT_A_DISK
    assert "/dev/sr0" not in pve7.read_devices()


def test_a_drive_without_smart_is_skipped(pve7: Host) -> None:
    drive = pve7.drive("sda.json")
    drive["smart_support"] = {"available": False}
    pve7.behave("sda.json", stdout=json.dumps(drive), exit_status=0)

    found = pve7.discover().devices[0]

    assert found.outcome is Outcome.SKIPPED
    assert found.reason is SkipReason.NO_SMART


def test_a_protocol_without_a_parser_is_unreadable(pve7: Host) -> None:
    drive = pve7.drive("sda.json")
    drive["device"] = {"name": "/dev/sda", "type": "test", "protocol": "TEST"}
    pve7.behave("sda.json", stdout=json.dumps(drive), exit_status=0)

    found = pve7.discover().devices[0]

    assert found.outcome is Outcome.UNREADABLE
    assert found.detail == "no parser for the protocol TEST"


# When parts of the host fail (FR-205)


def test_a_failed_scan_still_reads_the_manual_devices(pve7: Host) -> None:
    pve7.behave("scan.json", stdout="not json", exit_status=0)

    discovery = pve7.discover(devices=(ManualDevice("/dev/sda", "sat"),))

    assert discovery.scan_error == "the device scan answered without valid JSON"
    assert [found.outcome for found in discovery.devices] == [Outcome.MONITORED]
    # The version is still known from the drive.
    assert discovery.smartctl_version == (7, 5)


def test_a_scan_device_of_an_odd_form_is_not_passed_on(pve7: Host) -> None:
    scan = {
        "json_format_version": [1, 0],
        "devices": [{"name": "/dev/sda; reboot", "type": "sat", "protocol": "ATA"}],
    }
    pve7.behave("scan.json", stdout=json.dumps(scan), exit_status=0)

    found = pve7.discover().devices[0]

    assert found.outcome is Outcome.UNREADABLE
    assert pve7.read_devices() == []


def test_without_lsblk_the_drives_are_still_monitored(pve7: Host) -> None:
    pve7.lsblk_fails = True

    discovery = pve7.discover()

    assert discovery.enrichment_error == "lsblk did not answer"
    assert [found.outcome for found in discovery.devices] == [Outcome.MONITORED] * 3
    assert discovery.devices[0].snapshot is not None
    assert discovery.devices[0].snapshot.membership.volume_group is None


def test_the_links_below_dev_disk_are_found(pve7: Host) -> None:
    by_id = pve7.paths.disk_links / "by-id"
    by_path = pve7.paths.disk_links / "by-path"
    by_id.mkdir(parents=True)
    by_path.mkdir(parents=True)
    (by_id / "ata-Samsung_SSD_850_EVO_250GB_ANON-SN-0001").symlink_to("../../sda")
    (by_id / "ata-Samsung_SSD_850_EVO_250GB_ANON-SN-0001-part1").symlink_to("../../sda1")
    (by_path / "pci-0000:00:17.0-ata-1").symlink_to("../../sda")

    location = pve7.discover().devices[0].details.location

    assert location.by_id == (str(by_id / "ata-Samsung_SSD_850_EVO_250GB_ANON-SN-0001"),)
    assert location.by_path == str(by_path / "pci-0000:00:17.0-ata-1")


# Enrichment


@pytest.mark.parametrize(
    ("name", "group"),
    [
        ("pve-root", "pve"),
        ("pve-data-tpool", "pve"),
        ("pm961--a-data_tmeta", "pm961-a"),
        ("vg_data-vm--104--disk--0", "vg_data"),
        ("nodash", None),
    ],
)
def test_the_volume_group_is_read_from_the_device_mapper_name(name: str, group: str | None) -> None:
    # Verified against pvs on the test cluster (Research 06).
    assert volume_group_of(name) == group


def test_an_older_lsblk_writes_flags_as_text() -> None:
    stdout = json.dumps({"blockdevices": [{"name": "sdb", "type": "disk", "rm": "1"}]})

    devices = parse_block_devices(stdout)

    assert devices.devices["sdb"]["rm"] == "1"
    assert devices.error is None


def test_lsblk_without_json_is_an_error_of_enrichment() -> None:
    assert parse_block_devices("lsblk: unknown column").error == "lsblk answered without valid JSON"


# The per-drive overrides (FR-403)


def test_a_drive_excluded_by_an_override_is_skipped(pve7: Host) -> None:
    drives = (
        DriveOverride(
            selector=DriveSelector(SelectorKind.SERIAL, "ANON-SN-0001"),
            comment="Worn, replacement ordered",
            exclude=True,
        ),
    )

    discovery = pve7.discover(drives=drives)

    assert discovery.devices[0].outcome is Outcome.SKIPPED
    assert discovery.devices[0].reason is SkipReason.EXCLUDED
    assert discovery.devices[0].detail == 'serial = "ANON-SN-0001", per-drive override'
    assert [found.outcome for found in discovery.devices[1:]] == [
        Outcome.MONITORED,
        Outcome.MONITORED,
    ]


def test_a_drive_with_another_detail_level_is_read_again(pve7: Host) -> None:
    drives = (
        DriveOverride(
            selector=DriveSelector(SelectorKind.MODEL, "Samsung SSD 850 EVO*"),
            detail=Detail.BASIC,
        ),
    )

    discovery = pve7.discover(drives=drives)

    # The first read answers with the level of the configuration, the second
    # with the level of the override, so the drive was read twice.
    assert discovery.devices[0].outcome is Outcome.MONITORED
    calls = pve7.read_devices()
    assert len(calls) == 4
    assert calls.count("/dev/sda") == 2
    log = [json.loads(line) for line in pve7.log.read_text(encoding="utf-8").splitlines()]
    sda_calls = [call for call in log if call[-1] == "/dev/sda"]
    assert "--xall" in sda_calls[0]
    assert "--all" in sda_calls[1]
