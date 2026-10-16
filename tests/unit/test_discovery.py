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
from hosts import RECORDINGS, Host

from pve_smart_alert.config import (
    Detail,
    DriveOverride,
    DriveSelector,
    ManualDevice,
    SelectorKind,
)
from pve_smart_alert.discovery import (
    Candidate,
    Found,
    Outcome,
    SkipReason,
    Source,
)
from pve_smart_alert.discovery.enrichment import (
    HostPaths,
    parse_block_devices,
    scsi_host_driver,
    volume_group_of,
)
from pve_smart_alert.model import DriveClass

FIXTURES = RECORDINGS.parent
# The scan entry of a logical volume of a MegaRAID controller, in the words
# of smartmontools 7.4 and 7.5, which are the same (`os_linux.cpp` line 2652).
LOGICAL_VOLUME_ERROR = "DELL or MegaRaid controller, please try adding '-d megaraid,N'"


@pytest.fixture
def pve7(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host.of_node(tmp_path, monkeypatch, "pve7")


@pytest.fixture
def megaraid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    """The Telegraf recording: a SATA drive behind a MegaRAID controller on SCSI host 6."""
    return Host(tmp_path, monkeypatch, FIXTURES / "megaraid" / "telegraf-megaraid")


def sas_behind_megaraid(
    host: Host, device_id: int, *, without: tuple[str, ...] = (), **changes: object
) -> dict[str, object]:
    """Add a SAS drive behind the controller, derived from a recording of libblockdev.

    No public recording has a SAS drive read as `megaraid,N` (Research 08);
    this one is the SEAGATE ST600MP0036 with its device changed and its
    identifiers renumbered.
    """
    path = RECORDINGS / "libblockdev-seagate-st600mp0036" / "sdb.json"
    document: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    document["device"] = {
        "name": "/dev/bus/6",
        "info_name": f"/dev/bus/6 [megaraid_disk_{device_id:02d}]",
        "type": f"megaraid,{device_id}",
        "protocol": "SCSI",
    }
    document["serial_number"] = f"ANON-SN-{device_id + 100:04d}"
    document["logical_unit_id"] = f"0x5000c500{device_id + 100:08x}"
    document.update(changes)
    for key in without:
        del document[key]
    host.add_file(
        f"bus6-megaraid{device_id}.json",
        document,
        device="/dev/bus/6",
        device_type=f"megaraid,{device_id}",
    )
    return document


def found_of(host: Host, device_type: str) -> Found:
    """Return the device of this type that the scan of the recording lists."""
    return next(item for item in host.discover().devices if item.candidate.type == device_type)


def write_lsblk(host: Host, *disks: dict[str, object]) -> None:
    (host.recording / "lsblk.json").write_text(
        json.dumps({"blockdevices": list(disks)}), encoding="utf-8"
    )


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


def test_a_logical_volume_is_skipped_by_its_inquiry_data_in_lsblk(pve7: Host) -> None:
    # Signal 1 of ADR 0028: before the device is read.
    pve7.change_lsblk("sda", vendor="DELL    ", model="PERC H730P Mini")

    found = pve7.discover().devices[0]

    assert found.outcome is Outcome.SKIPPED
    assert found.reason is SkipReason.LOGICAL_VOLUME
    assert found.detail == "lsblk vendor DELL, model PERC H730P Mini"
    assert "/dev/sda" not in pve7.read_devices()


@pytest.mark.parametrize(
    ("vendor", "model", "volume"),
    [
        ("DELL", "PERC H730P Mini", True),
        ("dell", "perch710", True),
        ("BROADCOM", "PERC H330 Adapter", True),
        ("MegaRAID", "LD 0 RAID1 1M", True),
        ("LSI", "MR9361-8i", True),
        ("Intel", "Raid 1 Volume", True),
        ("Intel", "Raid 10 Volume", True),
        ("ATA", "Samsung SSD 850 EVO 250GB", False),
        ("DELL", "Virtual Disk", False),
        ("LSILOGIC", "Logical Volume", False),
        ("Intel", "SSDSC2KB480G8", False),
        (None, "SAMSUNG MZVLW256HEHP-000L2", False),
    ],
)
def test_the_inquiry_data_of_logical_volumes(
    pve7: Host, vendor: str | None, model: str, volume: bool
) -> None:
    # The list of ADR 0028; it grows with recordings.
    pve7.change_lsblk("sda", vendor=vendor, model=model)

    found = pve7.discover().devices[0]

    assert (found.reason is SkipReason.LOGICAL_VOLUME) is volume
    assert (found.outcome is Outcome.MONITORED) is not volume


def test_a_logical_volume_is_skipped_by_the_inquiry_data_of_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Signal 2 of ADR 0028, with the keys `vendor` and `product` of
    # smartmontools 7.0: the Intel RAID 1 volume of Scrutiny, which smartctl
    # reads without an error (Research 08).
    host = Host(tmp_path, monkeypatch, FIXTURES / "intel-rst" / "scrutiny-raid1-volume")
    host.set_scan({"name": "/dev/sdb", "type": "scsi", "protocol": "SCSI"})

    found = host.discover().devices[0]

    assert found.outcome is Outcome.SKIPPED
    assert found.reason is SkipReason.LOGICAL_VOLUME
    assert (
        found.detail == "the inquiry data of the drive output: vendor Intel, product Raid 1 Volume"
    )
    assert found.snapshot is None
    assert host.read_devices() == ["/dev/sdb"]


def test_the_inquiry_data_of_smartmontools_7_3_name_a_logical_volume(
    megaraid: Host,
) -> None:
    # The keys `scsi_vendor` and `scsi_product` of 7.3 and later. A volume
    # read with `--device=scsi` carries no message (ADR 0028).
    volume = sas_behind_megaraid(megaraid, 0)
    volume.update(scsi_vendor="DELL", scsi_product="PERC H730P Mini")
    volume["device"] = {"name": "/dev/sda", "type": "scsi", "protocol": "SCSI"}
    megaraid.add_file("sda.json", volume, device="/dev/sda", device_type="scsi")
    megaraid.set_scan({"name": "/dev/sda", "type": "scsi", "protocol": "SCSI"})

    found = megaraid.discover().devices[0]

    assert found.reason is SkipReason.LOGICAL_VOLUME
    assert found.detail == (
        "the inquiry data of the drive output: vendor DELL, product PERC H730P Mini"
    )


def test_a_logical_volume_is_skipped_by_the_message_of_the_scan(pve7: Host) -> None:
    # Signal 3 of ADR 0028, in the wording of smartmontools 7.4 and 7.5.
    scan = pve7.drive("scan.json")
    devices = scan["devices"]
    assert isinstance(devices, list)
    devices[0]["open_error"] = LOGICAL_VOLUME_ERROR
    (pve7.recording / "scan.json").write_text(json.dumps(scan), encoding="utf-8")

    found = pve7.discover().devices[0]

    assert found.candidate.open_error == LOGICAL_VOLUME_ERROR
    assert found.outcome is Outcome.SKIPPED
    assert found.reason is SkipReason.LOGICAL_VOLUME
    assert found.detail == "the scan: smartctl asks for -d megaraid,N"
    assert "/dev/sda" not in pve7.read_devices()


@pytest.mark.parametrize(
    "message",
    [
        "DELL or MegaRaid controller, please try adding '--device=megaraid,N'",
        "Smartctl open device: /dev/sda failed: DELL or MegaRaid controller",
    ],
)
def test_a_reworded_message_is_not_taken_for_a_logical_volume(pve7: Host, message: str) -> None:
    # The message is matched by its part "-d megaraid,N" only; without it
    # the device is read like any other (ADR 0028).
    scan = pve7.drive("scan.json")
    devices = scan["devices"]
    assert isinstance(devices, list)
    devices[0]["open_error"] = message
    (pve7.recording / "scan.json").write_text(json.dumps(scan), encoding="utf-8")

    found = pve7.discover().devices[0]

    assert found.outcome is Outcome.MONITORED
    assert "/dev/sda" in pve7.read_devices()


@pytest.mark.parametrize(
    ("value", "name", "detail"),
    [
        (13, "enclosure", "SCSI peripheral device type 13, enclosure"),
        (12, "storage array", "SCSI peripheral device type 12, storage array"),
        (3, None, "SCSI peripheral device type 3"),
    ],
)
def test_a_device_that_is_not_a_disk_by_its_peripheral_type_is_skipped(
    megaraid: Host, value: int, name: str | None, detail: str
) -> None:
    # An enclosure answers through the controller like a drive (ADR 0028).
    # Derived: no recording of one is public (Research 08).
    device_type: dict[str, object] = {"scsi_value": value}
    if name is not None:
        device_type["name"] = name
    # The recorded scan lists `megaraid,13`; the output has no model name.
    sas_behind_megaraid(megaraid, 13, without=("scsi_model_name",), device_type=device_type)

    found = found_of(megaraid, "megaraid,13")

    assert found.outcome is Outcome.SKIPPED
    assert found.reason is SkipReason.NOT_A_DISK
    assert found.detail == detail
    assert found.details.location.device_id == "13"


def test_a_simplified_direct_access_device_is_a_disk(megaraid: Host) -> None:
    sas_behind_megaraid(megaraid, 8, device_type={"scsi_value": 14})

    found = found_of(megaraid, "megaraid,8")

    assert found.outcome is Outcome.MONITORED


# Drives behind a MegaRAID controller (ADR 0028)


@pytest.mark.parametrize(
    ("name", "device_type"),
    [
        ("/dev/bus/6", "sat+megaraid,14"),
        ("/dev/bus/0", "megaraid,0"),
        ("/dev/sda", "sat+megaraid,1"),
    ],
)
def test_the_pass_through_types_of_megaraid_reach_smartctl(name: str, device_type: str) -> None:
    assert Candidate(name, device_type, Source.SCAN).valid
    assert Candidate(name, device_type, Source.MANUAL).valid


def test_a_sata_drive_behind_megaraid_is_read_as_ata(megaraid: Host) -> None:
    # The SATA hard disk of the Telegraf recording, as the configuration
    # names it; the recorded scan lists it as `megaraid,14`.
    megaraid.scsi_host(6, "megaraid_sas")

    found = megaraid.discover(devices=(ManualDevice("/dev/bus/6", "sat+megaraid,14"),)).devices[-1]

    assert found.outcome is Outcome.MONITORED
    snapshot = found.snapshot
    assert snapshot is not None
    assert snapshot.identity.model == "ST6000NM0115-1YZ110"
    assert snapshot.drive_class is DriveClass.HDD
    assert "ata.attr.197.raw" in snapshot.metrics
    assert snapshot.location.controller == "/dev/bus/6 (megaraid_sas)"
    assert snapshot.location.device_id == "14"
    assert snapshot.location.controller_text == "/dev/bus/6 (megaraid_sas), device 14"
    log = [json.loads(line) for line in megaraid.log.read_text(encoding="utf-8").splitlines()]
    assert log[-1][-3:] == ["--device=sat+megaraid,14", "--nocheck=standby", "/dev/bus/6"]


def test_the_parser_follows_the_protocol_of_the_output(megaraid: Host) -> None:
    # The recorded scan lists the SATA drive as `megaraid,14` with the
    # protocol SCSI; smartctl answers for it as ATA.
    sata = megaraid.drive("bus6-megaraid14.json")
    megaraid.add_file("scanned.json", sata, device="/dev/bus/6", device_type="megaraid,14")

    found = found_of(megaraid, "megaraid,14")

    assert found.candidate.protocol == "SCSI"
    assert found.outcome is Outcome.MONITORED
    assert found.snapshot is not None
    assert "ata.attr.197.raw" in found.snapshot.metrics


def test_a_sas_drive_behind_megaraid_is_read_as_scsi(megaraid: Host) -> None:
    # The recorded scan lists it as `megaraid,8` with the protocol SCSI.
    megaraid.scsi_host(6, "megaraid_sas")
    sas_behind_megaraid(megaraid, 8)

    found = found_of(megaraid, "megaraid,8")

    assert found.outcome is Outcome.MONITORED
    snapshot = found.snapshot
    assert snapshot is not None
    assert snapshot.identity.model == "SEAGATE ST600MP0036"
    assert "scsi.grown_defects" in snapshot.metrics
    assert snapshot.location.controller_text == "/dev/bus/6 (megaraid_sas), device 8"
    log = [json.loads(line) for line in megaraid.log.read_text(encoding="utf-8").splitlines()]
    (call,) = [call for call in log if "--device=megaraid,8" in call]
    assert call[-2:] == ["--device=megaraid,8", "/dev/bus/6"]


def test_without_the_driver_in_sysfs_the_controller_is_its_node(megaraid: Host) -> None:
    found = megaraid.discover(devices=(ManualDevice("/dev/bus/6", "sat+megaraid,14"),)).devices[-1]

    assert found.details.location.controller == "/dev/bus/6"
    assert found.details.location.device_id == "14"


def test_the_driver_of_a_scsi_host_is_read_from_sysfs(tmp_path: Path) -> None:
    paths = HostPaths(sysfs=tmp_path)
    proc_name = tmp_path / "class" / "scsi_host" / "host2" / "proc_name"
    proc_name.parent.mkdir(parents=True)
    proc_name.write_text("mpt3sas\n", encoding="utf-8")

    assert scsi_host_driver(2, paths) == "mpt3sas"
    assert scsi_host_driver("3", paths) is None
    proc_name.write_text("\n", encoding="utf-8")
    assert scsi_host_driver(2, paths) is None


def test_lsblk_of_the_node_does_not_describe_a_drive_behind_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scrutiny reads its drives as `sat+megaraid,N` on /dev/sda, which is
    # the logical volume: its inquiry data in lsblk are not those of the
    # drive, which is read and not skipped.
    host = Host(tmp_path, monkeypatch, FIXTURES / "megaraid" / "scrutiny-megaraid-wd4000fyyx")
    host.set_scan({"name": "/dev/sda", "type": "sat+megaraid,0", "protocol": "ATA"})
    write_lsblk(
        host,
        {"name": "sda", "kname": "sda", "type": "disk", "vendor": "DELL", "model": "PERC H730"},
    )

    found = host.discover().devices[0]

    assert found.outcome is Outcome.MONITORED
    assert found.details.block_device is False
    assert found.details.location.controller_text == "/dev/sda, device 0"


def test_a_drive_in_jbod_mode_is_kept_once_as_its_block_device(megaraid: Host) -> None:
    # In JBOD mode the drive is a block device of the host and is reached
    # through the controller as well (ADR 0005, FR-106). The block device
    # is kept although the scan lists the other path first.
    sata = megaraid.drive("bus6-megaraid14.json")
    sata["device"] = {"name": "/dev/sdc", "type": "sat", "protocol": "ATA"}
    megaraid.add_file("sdc.json", sata, device="/dev/sdc", device_type="sat")
    megaraid.set_scan(
        {"name": "/dev/bus/6", "type": "sat+megaraid,14", "protocol": "ATA"},
        {"name": "/dev/sdc", "type": "sat", "protocol": "ATA"},
    )
    write_lsblk(
        megaraid,
        {"name": "sdc", "kname": "sdc", "type": "disk", "vendor": "ATA", "model": "ST6000NM0115"},
    )

    through_controller, block_device = megaraid.discover().devices

    assert block_device.outcome is Outcome.MONITORED
    assert block_device.snapshot is not None
    assert block_device.snapshot.access.aliases == ("/dev/bus/6",)
    assert through_controller.outcome is Outcome.SKIPPED
    assert through_controller.reason is SkipReason.DUPLICATE
    assert through_controller.detail == "the same drive as /dev/sdc"


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
