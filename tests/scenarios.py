#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scenarios for the fake smartctl: a host whose drives change step by step (ADR 0016).

A scenario is a base recording of `fixtures/smartctl/` and a sequence of
steps. Each step is a whole recording directory, derived from the base by
changing values, adding copies of a drive or removing one, that the fake
smartctl replays when FAKE_SMARTCTL_RECORDING names it. The steps are
derived, not recorded; the base recordings are listed in
`fixtures/SOURCES.md`.

The MegaRAID scenarios combine two public recordings into one host, because
no public recording has a SAS drive read as `megaraid,N`: the SATA drive of
the Telegraf recording, and a SAS drive of libblockdev moved behind the
controller. The SAS drive behind the controller, the logical volume, the
answer of the scan with `--scan-open` and lsblk are derived, not recorded
(Research 08, Q-R1).

The scenario tests build the steps in a temporary directory. For the
acceptance on a real host the same steps are written with

    python3 tests/scenarios.py build pending-sectors /root/scenario

and each step is run with

    FAKE_SMARTCTL_RECORDING=/root/scenario/03-pending-3 pve-smart-alert check

while `smartctl.path` of the configuration points at `tests/fake-smartctl`.

Only the standard library is used, so that the script runs on a host
without the development tools.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

RECORDINGS: Final = Path(__file__).resolve().parent / "fixtures" / "smartctl"

# The host of the MegaRAID scenarios: the controller is SCSI host 6, as in
# the Telegraf recording.
MEGARAID_BASE: Final = "megaraid/telegraf-megaraid"
MEGARAID_NODE: Final = "/dev/bus/6"
MEGARAID_SATA: Final = "bus6-megaraid14.json"
MEGARAID_SAS: Final = "bus6-megaraid8.json"
# The SAS hard disk that is moved behind the controller.
DERIVED_SAS_SOURCE: Final = ("direct/libblockdev-seagate-st600mp0036", "sdb.json")
# What the scan writes to `open_error` for a logical volume of a MegaRAID
# controller, in 7.4 and 7.5 alike (`os_linux.cpp` line 2652, ADR 0028).
LOGICAL_VOLUME_ERROR: Final = "DELL or MegaRaid controller, please try adding '-d megaraid,N'"

# The host of the HPE scenario: the controller is SCSI host 1 of the driver
# hpsa, and the probe reads through its SCSI generic node (ADR 0032).
HPE_NODE: Final = "/dev/sg1"
# The two drives behind it, from the recording of the maintainer's TrueNAS
# host: a SATA SSD and a SAS SSD, so that both protocols are read.
HPE_BASE: Final = "hba/maintainer-truenas"
HPE_DRIVES: Final = (("cciss0.json", "sdd.json", "cciss,0"), ("cciss1.json", "sdc.json", "cciss,1"))

# The drives of the scenario `manual-pass-through`, one per controller type of
# smartctl(8) of 7.4 and 7.5 besides MegaRAID and cciss (Research 04,
# ADR 0034), on a node of the form the manual shows for Linux: the file of
# the step, the node, the type, the recorded drive it is made of, and whether
# a manual entry names it. The scan of smartctl lists the drives of an
# SSSRAID controller by itself (`get_dev_sssraid` in os_linux.cpp of 7.4 and
# 7.5); the others only a manual entry reaches. `/dev/sdc` and `/dev/sdd` are
# logical volumes of the host, as the manual's `/dev/sda` is for `aacraid`
# and `hpt`; the base recording has `/dev/sda` and `/dev/sdb` already.
MANUAL_DRIVES: Final = (
    (
        "areca2.json",
        "/dev/sg2",
        "areca,2",
        "megaraid/scrutiny-megaraid-wd4000fyyx",
        "sda-megaraid0.json",
        True,
    ),
    (
        "areca1-1.json",
        "/dev/sg3",
        "areca,1/1",
        "direct/libblockdev-seagate-st600mp0036",
        "sdb.json",
        True,
    ),
    ("3ware1.json", "/dev/twa0", "3ware,1", "direct/test-cluster-pve5", "sda.json", True),
    ("aacraid0-0-2.json", "/dev/sdc", "aacraid,0,0,2", "hba/maintainer-truenas", "sdc.json", True),
    ("hpt1-2-3.json", "/dev/sdd", "hpt,1/2/3", "direct/test-cluster-pve6", "sda.json", True),
    (
        "sssraid0-1.json",
        "/dev/bsg/sssraid0",
        "sssraid,0,1",
        "direct/libblockdev-toshiba-al15seb120ny",
        "sdd.json",
        False,
    ),
)
MANUAL_BASE: Final = "direct/standalone-pve1"

# A recording in memory: file name to JSON document. `recording.json` and
# `scan.json` are documents like the others.
Documents = dict[str, dict[str, object]]
Edit = Callable[[Documents], None]


@dataclass(frozen=True)
class Step:
    """One state of the host: a name and the edits that make it from the base."""

    name: str
    edits: tuple[Edit, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class Scenario:
    """A base recording and the steps derived from it."""

    name: str
    base: str
    description: str
    steps: tuple[Step, ...]
    prepare: tuple[Edit, ...] = ()
    # What the host has besides the recording, which the frame of the tests
    # writes and a real host brings itself: the drivers of the SCSI hosts of
    # sysfs by host number, the SCSI generic nodes by the host they belong
    # to, and the manual entries of the configuration as name and type
    # (FR-104).
    scsi_hosts: Mapping[int, str] = field(default_factory=dict)
    sg_nodes: Mapping[int, int] = field(default_factory=dict)
    devices: tuple[tuple[str, str], ...] = ()


def attribute(file: str, number: int, raw: int) -> Edit:
    """Set the raw value of an ATA attribute, adding the attribute when it is missing."""

    def edit(documents: Documents) -> None:
        table = _attribute_table(documents[file])
        for entry in table:
            if entry.get("id") == number:
                entry["raw"] = {"value": raw, "string": str(raw)}
                return
        table.append(
            {
                "id": number,
                "name": f"Attribute_{number}",
                "value": 100,
                "worst": 100,
                "thresh": 0,
                "when_failed": "",
                "flags": {"value": 50, "string": "-O--CK ", "prefailure": False},
                "raw": {"value": raw, "string": str(raw)},
            }
        )

    return edit


def temperature(file: str, celsius: int) -> Edit:
    """Set the current temperature a drive reports."""

    def edit(documents: Documents) -> None:
        section = documents[file].setdefault("temperature", {})
        assert isinstance(section, dict)
        section["current"] = celsius

    return edit


def remove(device: str) -> Edit:
    """Take a drive away: out of the scan and out of the recording."""

    def edit(documents: Documents) -> None:
        scan = documents["scan.json"]
        devices = scan.get("devices")
        assert isinstance(devices, list)
        scan["devices"] = [entry for entry in devices if entry.get("name") != device]
        recording = documents["recording.json"]
        files = recording.get("files")
        assert isinstance(files, list)
        gone = [entry["file"] for entry in files if entry.get("device") == device]
        recording["files"] = [entry for entry in files if entry.get("device") != device]
        for file in gone:
            documents.pop(file, None)

    return edit


def remove_file(file: str) -> Edit:
    """Take away the drive of one recording file, which may share its device node.

    Drives behind a controller share the device node, so `remove` would take
    all of them; this edit takes the one of `file`, by node and type.
    """

    def edit(documents: Documents) -> None:
        device = _device_of(documents[file])
        scan = documents["scan.json"]
        devices = scan.get("devices")
        assert isinstance(devices, list)
        scan["devices"] = [
            entry
            for entry in devices
            if (entry.get("name"), entry.get("type")) != (device["name"], device["type"])
        ]
        recording = documents["recording.json"]
        files = recording.get("files")
        assert isinstance(files, list)
        recording["files"] = [entry for entry in files if entry.get("file") != file]
        del documents[file]

    return edit


def copies(file: str, count: int) -> Edit:
    """Make `count` drives of one: the copies get the next device names and serial numbers.

    The serial numbers follow the placeholders of the anonymization
    (ADR 0023), so that no copy carries a real one.
    """

    def edit(documents: Documents) -> None:
        source = documents[file]
        device = _device_of(source)
        stem = device["name"].removeprefix("/dev/")
        scan = documents["scan.json"]
        devices = scan["devices"]
        recording = documents["recording.json"]
        files = recording["files"]
        assert isinstance(devices, list)
        assert isinstance(files, list)
        entry = next(item for item in files if item.get("file") == file)
        for number in range(2, count + 1):
            name = f"/dev/{stem[:-1]}{chr(ord(stem[-1]) + number - 1)}"
            document = copy.deepcopy(source)
            document["serial_number"] = f"ANON-SN-{number:04d}"
            document.pop("wwn", None)
            document["device"] = {**_device_of(document), "name": name}
            new_file = f"{name.removeprefix('/dev/')}.json"
            documents[new_file] = document
            devices.append(
                {
                    "name": name,
                    "info_name": f"{name} [SAT]",
                    "type": device["type"],
                    "protocol": device.get("protocol", "ATA"),
                }
            )
            files.append({**entry, "file": new_file, "device": name})

    return edit


def megaraid_host(*, jbod: bool = False) -> Edit:
    """Make the MegaRAID host of the scenarios from the Telegraf recording.

    The host has, behind the controller on `/dev/bus/6`, the recorded SATA
    hard disk as `sat+megaraid,14` and a derived SAS hard disk as
    `megaraid,8`, and a logical volume `/dev/sda` that lsblk shows with the
    inquiry data of a PERC controller and the scan with its `open_error`.
    The SAS drive is the libblockdev recording of a SEAGATE ST600MP0036
    with its device changed, and its serial number and logical unit id
    renumbered to the second placeholder (ADR 0023). With `jbod`, the SATA
    drive is also a block device of the host, `/dev/sdc`, as a drive in
    JBOD mode is.

    The recorded scan was made without `--scan-open` and lists every drive
    as `megaraid,N`; it is replaced by what `--scan-open` lists, which
    opens each drive and names a SATA drive `sat+megaraid,N`. That answer
    and lsblk are derived from the source code of smartmontools, not
    recorded (Research 08, Q-R1).
    """

    def edit(documents: Documents) -> None:
        sata = documents[MEGARAID_SATA]
        directory, file = DERIVED_SAS_SOURCE
        sas = json.loads((RECORDINGS / directory / file).read_text(encoding="utf-8"))
        sas["serial_number"] = "ANON-SN-0002"
        sas["logical_unit_id"] = "0x5000c50000000002"
        _place(sas, MEGARAID_NODE, "megaraid,8")
        documents[MEGARAID_SAS] = sas

        devices: list[dict[str, object]] = [
            {
                "name": "/dev/sda",
                "info_name": "/dev/sda",
                "type": "scsi",
                "protocol": "SCSI",
                "open_error": LOGICAL_VOLUME_ERROR,
            },
            _scan_entry(sata),
            _scan_entry(sas),
        ]
        files: list[dict[str, object]] = [
            {"file": "scan.json", "command": "smartctl --scan-open --json=c", "exit_status": 0},
            _recording_entry(MEGARAID_SATA, sata, exit_status=4),
            _recording_entry(MEGARAID_SAS, sas, exit_status=0),
        ]
        disks: list[dict[str, object]] = [
            {
                "name": "sda",
                "kname": "sda",
                "type": "disk",
                "tran": None,
                "vendor": "DELL    ",
                "model": "PERC H730P Mini",
            }
        ]
        if jbod:
            block = copy.deepcopy(sata)
            _place(block, "/dev/sdc", "sat")
            documents["sdc.json"] = block
            devices.insert(1, _scan_entry(block))
            files.insert(1, _recording_entry("sdc.json", block, exit_status=4))
            disks.append(
                {
                    "name": "sdc",
                    "kname": "sdc",
                    "type": "disk",
                    "tran": None,
                    "vendor": "ATA     ",
                    "model": sata["model_name"],
                }
            )

        scan = documents["scan.json"]
        scan["devices"] = devices
        smartctl = scan["smartctl"]
        assert isinstance(smartctl, dict)
        smartctl["argv"] = ["smartctl", "--scan-open", "--json=c"]
        recording = documents["recording.json"]
        recording["origin"] = (
            "Derived for the MegaRAID scenarios of tests/scenarios.py: the SATA drive of the"
            " Telegraf recording, a SAS drive of libblockdev moved behind the controller, a"
            " logical volume, the scan of --scan-open and lsblk; only the SATA drive is recorded"
        )
        recording["files"] = files
        documents["lsblk.json"] = {"blockdevices": disks}

    return edit


def hpe_host() -> Edit:
    """Make a host with an HPE Smart Array controller of two drives (ADR 0032).

    Nothing of such a host was ever recorded (Research 08), so the host is
    synthetic: the SATA SSD and a SAS SSD of the TrueNAS recording, with the
    device fields of a read of `cciss,N` on `/dev/sg1`, and the rest of the
    recording taken away. The scan lists no device, because what smartctl
    makes of the logical volume of an HPE controller is not recorded either
    (Q-R2). A device ID that the recording does not have is an empty bay:
    the fake smartctl answers as smartctl does, with a failed open.
    """

    def edit(documents: Documents) -> None:
        drives = {file: documents[source] for file, source, _ in HPE_DRIVES}
        documents.clear()
        files: list[dict[str, object]] = []
        for file, _, device_type in HPE_DRIVES:
            document = copy.deepcopy(drives[file])
            device = _device_of(document)
            device["name"] = HPE_NODE
            device["type"], device["info_name"] = _written_type(
                HPE_NODE, device_type, device.get("protocol")
            )
            smartctl = document["smartctl"]
            assert isinstance(smartctl, dict)
            smartctl["argv"] = [
                "smartctl",
                "--xall",
                "--json=c",
                f"--device={device_type}",
                HPE_NODE,
            ]
            documents[file] = document
            files.append({"file": file, "device": HPE_NODE, "type": device_type, "exit_status": 0})
        documents["scan.json"] = {
            "json_format_version": [1, 0],
            "smartctl": {"version": [7, 5], "argv": ["smartctl", "--scan-open", "--json=c"]},
            "devices": [],
        }
        documents["recording.json"] = {
            "origin": (
                "Synthetic, written for slice 5 of milestone M6 (ADR 0032): two devices"
                " of the recording of the maintainer's TrueNAS host, with the device"
                " fields of a cciss,N read. No HPE Smart Array host was ever recorded"
            ),
            "license": "AGPL-3.0-or-later",
            "node": "hpe1",
            "collected": "synthetic",
            "collected_with": "tests/scenarios.py",
            "smartmontools": "7.5",
            "controller": f"HPE Smart Array behind hpsa, read on {HPE_NODE} (synthetic)",
            "files": [
                {"file": "scan.json", "command": "smartctl --scan-open --json=c", "exit_status": 0},
                *files,
            ],
        }

    return edit


def manual_host() -> Edit:
    """Add a drive behind each controller other than MegaRAID and cciss (ADR 0034).

    Each drive of `MANUAL_DRIVES` is a recorded drive of another fixture,
    moved to the node and type of its controller and given the next
    placeholder serial number, without WWN or logical unit id (ADR 0023).
    The project has no recording of a drive behind these controllers, so the
    drives are derived; their `info_name` is the one the source of
    smartmontools writes (os_linux.cpp of 7.5), and the rest of their device
    fields is not known (Q-R9). The scan lists the recorded on-board drive and
    the SSSRAID drive; how it would list a logical volume of these
    controllers is not known, and it lists none. lsblk shows the two logical
    volumes `/dev/sdc` and `/dev/sdd` that `aacraid` and `hpt` read through,
    the first with a ZFS pool, and the frame names the other drives as
    manual entries.
    """

    def edit(documents: Documents) -> None:
        files = documents["recording.json"]["files"]
        devices = documents["scan.json"]["devices"]
        assert isinstance(files, list)
        assert isinstance(devices, list)
        for number, entry in enumerate(MANUAL_DRIVES, start=2):
            file, name, device_type, base, source, manual = entry
            path = RECORDINGS / base / source
            document = json.loads(path.read_text(encoding="utf-8"))
            document["serial_number"] = f"ANON-SN-{number:04d}"
            document.pop("wwn", None)
            document.pop("logical_unit_id", None)
            _place(document, name, device_type)
            documents[file] = document
            files.append(_recording_entry(file, document, exit_status=0, device_type=device_type))
            if not manual:
                devices.append(_scan_entry(document, device_type))
        recording = documents["recording.json"]
        recording["origin"] = (
            "Derived for the scenario manual-pass-through of tests/scenarios.py: the"
            " on-board SATA SSD of pve-test, and one recorded drive of another fixture"
            " behind each controller other than MegaRAID and cciss; only the on-board"
            " drive is recorded on this host"
        )
        lsblk = documents["lsblk.json"]["blockdevices"]
        assert isinstance(lsblk, list)
        assert not {"sdc", "sdd"} & {device.get("name") for device in lsblk}
        lsblk.append(
            {
                "name": "sdc",
                "kname": "sdc",
                "type": "disk",
                "tran": "sas",
                "children": [
                    {
                        "name": "sdc1",
                        "kname": "sdc1",
                        "type": "part",
                        "fstype": "zfs_member",
                        "label": "tank",
                    }
                ],
            }
        )
        lsblk.append({"name": "sdd", "kname": "sdd", "type": "disk", "tran": None})

    return edit


def standby(file: str, mode: str) -> Edit:
    """Make the drive of one file answer that it is in standby, as smartctl does.

    The fake smartctl answers so when the tool asks it not to wake the drive;
    a SCSI drive names its power condition in words, such as STANDBY BY TIMER
    (scsiprint.cpp of 7.4 and 7.5).
    """

    def edit(documents: Documents) -> None:
        behavior = documents.setdefault("behavior.json", {})
        behavior[file] = {"standby": mode}

    return edit


def media_errors(file: str, count: int) -> Edit:
    """Set the media and data integrity errors of an NVMe drive."""

    def edit(documents: Documents) -> None:
        log = documents[file]["nvme_smart_health_information_log"]
        assert isinstance(log, dict)
        log["media_errors"] = count

    return edit


def device_id(file: str, number: int) -> Edit:
    """Give a drive behind the controller another device ID, as after a rebuild or a reboot."""

    def edit(documents: Documents) -> None:
        document = documents[file]
        device = _device_of(document)
        old = device["type"]
        new = f"{old.rpartition(',')[0]},{number}"
        _place(document, device["name"], new)
        devices = documents["scan.json"]["devices"]
        files = documents["recording.json"]["files"]
        assert isinstance(devices, list)
        assert isinstance(files, list)
        for entry in devices:
            if entry["name"] == device["name"] and entry["type"] == old:
                entry.update(_scan_entry(document))
        for entry in files:
            if entry["file"] == file:
                entry["type"] = new

    return edit


def grown_defects(file: str, count: int) -> Edit:
    """Set the elements of the grown defect list of a SCSI drive."""

    def edit(documents: Documents) -> None:
        documents[file]["scsi_grown_defect_list"] = count

    return edit


#: The scenarios, by name. The steps of `pending-sectors` and `five-hot`
#: follow the acceptance steps of milestone M4 in ROADMAP.md. The others are
#: named after the controller family they show, as milestone M6 asks, and
#: `docs/hardware-support.md` names the scenario of every family.
SCENARIOS: Final = {
    scenario.name: scenario
    for scenario in (
        Scenario(
            name="pending-sectors",
            base="direct/standalone-pve1",
            description=(
                "One SATA SSD that gets pending sectors, gets worse, recovers and disappears"
            ),
            steps=(
                Step("01-healthy", description="first run: one summary"),
                Step("02-healthy", description="no change: nothing"),
                Step(
                    "03-pending-3",
                    (attribute("sda.json", 197, 3),),
                    "3 pending sectors: one warning",
                ),
                Step(
                    "04-pending-3",
                    (attribute("sda.json", 197, 3),),
                    "the same again: nothing",
                ),
                Step(
                    "05-pending-20",
                    (attribute("sda.json", 197, 20),),
                    "20 pending sectors: one error, escalated",
                ),
                Step("06-healthy", description="healthy again: nothing yet"),
                Step("07-healthy", description="healthy for the second run: one recovery"),
                Step("08-gone", (remove("/dev/sda"),), "the drive is gone: nothing yet"),
                Step(
                    "09-gone",
                    (remove("/dev/sda"),),
                    "gone for the second run: one missing drive",
                ),
            ),
        ),
        Scenario(
            name="five-hot",
            base="direct/standalone-pve1",
            description="Five SATA SSDs that get too hot at the same time",
            prepare=(copies("sda.json", 5),),
            steps=(
                Step("01-cool", description="first run: one summary"),
                Step(
                    "02-hot",
                    tuple(temperature(f"sd{letter}.json", 65) for letter in "abcde"),
                    "too hot, waiting for the confirmation: nothing",
                ),
                Step(
                    "03-hot",
                    tuple(temperature(f"sd{letter}.json", 65) for letter in "abcde"),
                    "confirmed: one summary instead of five",
                ),
            ),
        ),
        Scenario(
            name="onboard-sata-nvme",
            base="direct/test-cluster-pve7",
            description=(
                "A cluster node with a SATA SSD and two NVMe drives on the board,"
                " one of which gets media errors"
            ),
            scsi_hosts=dict.fromkeys(range(6), "ahci"),
            steps=(
                Step("01-healthy", description="first run: one summary with three drives"),
                Step(
                    "02-media-errors",
                    (media_errors("nvme0.json", 2),),
                    "2 media errors on the first NVMe drive: one warning, without device ID",
                ),
            ),
        ),
        Scenario(
            name="hba-sas",
            base="hba/maintainer-truenas",
            description=(
                "The TrueNAS host: three SAS SSDs behind an LSI SAS2308 HBA (mpt2sas)"
                " and a SATA SSD on the board, one SAS SSD gets grown defects"
            ),
            scsi_hosts={0: "mpt2sas", **dict.fromkeys(range(1, 7), "ahci"), 7: "ahciem"},
            steps=(
                Step(
                    "01-healthy",
                    description="first run: one summary with four drives, no controller notice",
                ),
                Step(
                    "02-grown-defects",
                    (grown_defects("sdc.json", 150),),
                    "150 grown defects on a SAS SSD: one warning, without device ID",
                ),
            ),
        ),
        Scenario(
            name="hpe-smart-array",
            base=HPE_BASE,
            description=(
                "A synthetic HPE Smart Array controller behind hpsa with a SATA and a SAS"
                " SSD that the probe finds, one of which gets pending sectors"
            ),
            prepare=(hpe_host(),),
            scsi_hosts={0: "ahci", 1: "hpsa"},
            sg_nodes={1: 1},
            steps=(
                Step("01-healthy", description="first run: one summary with two drives"),
                Step(
                    "02-pending-3",
                    (attribute("cciss0.json", 197, 3),),
                    "3 pending sectors on cciss,0: one warning naming controller and device ID",
                ),
            ),
        ),
        Scenario(
            name="unsupported-mpi3mr",
            base="direct/standalone-pve1",
            description=(
                "A host with a synthetic mpi3mr controller next to its on-board SATA SSD,"
                " whose drives smartctl cannot read"
            ),
            scsi_hosts={0: "ahci", 1: "ahci", 2: "mpi3mr"},
            steps=(
                Step(
                    "01-first",
                    description="first run: one summary and one notice about the controller",
                ),
                Step("02-again", description="no change: nothing"),
            ),
        ),
        Scenario(
            name="manual-pass-through",
            base=MANUAL_BASE,
            description=(
                "One derived drive behind each controller other than MegaRAID and cciss:"
                " Areca, 3ware, Adaptec and HighPoint through manual entries, SSSRAID"
                " from the scan"
            ),
            prepare=(manual_host(),),
            devices=tuple(
                (name, device_type)
                for _, name, device_type, _, _, manual in MANUAL_DRIVES
                if manual
            ),
            steps=(
                Step("01-healthy", description="first run: one summary with seven drives"),
                Step(
                    "02-degraded",
                    (attribute("3ware1.json", 197, 3), grown_defects("aacraid0-0-2.json", 150)),
                    "pending sectors behind 3ware and grown defects behind Adaptec:"
                    " one warning each, without device ID",
                ),
                Step(
                    "03-sas-standby",
                    (
                        attribute("3ware1.json", 197, 3),
                        grown_defects("aacraid0-0-2.json", 150),
                        standby("sssraid0-1.json", "STANDBY BY TIMER"),
                    ),
                    "the SAS drive behind SSSRAID is in standby: not woken, nothing",
                ),
            ),
        ),
        Scenario(
            name="megaraid-jbod",
            base=MEGARAID_BASE,
            scsi_hosts={6: "megaraid_sas"},
            description=(
                "A MegaRAID host whose SATA drive in JBOD mode is a block device as well,"
                " next to a logical volume and a derived SAS drive"
            ),
            prepare=(megaraid_host(jbod=True),),
            steps=(
                Step("01-first", description="first run: one summary with two drives"),
                Step("02-again", description="no change: nothing"),
            ),
        ),
        Scenario(
            name="megaraid-id-change",
            base=MEGARAID_BASE,
            scsi_hosts={6: "megaraid_sas"},
            description=(
                "Two drives behind a MegaRAID controller whose device IDs change while one"
                " has a finding, and then one of them is gone"
            ),
            prepare=(megaraid_host(),),
            steps=(
                Step("01-first", description="first run: one summary"),
                Step(
                    "02-pending-8",
                    (attribute(MEGARAID_SATA, 197, 8),),
                    "8 pending sectors on the SATA drive: one warning",
                ),
                Step(
                    "03-moved",
                    (
                        attribute(MEGARAID_SATA, 197, 8),
                        device_id(MEGARAID_SATA, 15),
                        device_id(MEGARAID_SAS, 9),
                    ),
                    "device IDs 15 and 9 instead of 14 and 8: nothing",
                ),
                Step(
                    "04-moved",
                    (
                        attribute(MEGARAID_SATA, 197, 8),
                        device_id(MEGARAID_SATA, 15),
                        device_id(MEGARAID_SAS, 9),
                    ),
                    "the same again: nothing, no drive missing",
                ),
                Step(
                    "05-gone",
                    (
                        attribute(MEGARAID_SATA, 197, 8),
                        device_id(MEGARAID_SATA, 15),
                        remove_file(MEGARAID_SAS),
                    ),
                    "the SAS drive is gone: nothing yet",
                ),
                Step(
                    "06-gone",
                    (
                        attribute(MEGARAID_SATA, 197, 8),
                        device_id(MEGARAID_SATA, 15),
                        remove_file(MEGARAID_SAS),
                    ),
                    "gone for the second run: one missing drive, with its last device ID 9",
                ),
            ),
        ),
        Scenario(
            name="megaraid-degraded",
            base=MEGARAID_BASE,
            scsi_hosts={6: "megaraid_sas"},
            description=(
                "A SATA and a derived SAS drive behind a MegaRAID controller that degrade"
                " at the same time"
            ),
            prepare=(megaraid_host(),),
            steps=(
                Step("01-healthy", description="first run: one summary"),
                Step(
                    "02-degraded",
                    (attribute(MEGARAID_SATA, 197, 3), grown_defects(MEGARAID_SAS, 150)),
                    "3 pending sectors and 150 grown defects: one warning per drive,"
                    " naming controller and device ID",
                ),
            ),
        ),
    )
}


def load(base: str) -> Documents:
    """Return the base recording as documents."""
    directory = RECORDINGS / base
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    }


def documents_of(scenario: Scenario, step: Step) -> Documents:
    """Return the recording of one step."""
    documents = copy.deepcopy(load(scenario.base))
    for edit in (*scenario.prepare, *step.edits):
        edit(documents)
    return documents


def write(documents: Documents, directory: Path) -> None:
    """Write a recording as a directory the fake smartctl can replay."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    for name, document in documents.items():
        (directory / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def build(scenario: Scenario, directory: Path) -> list[Path]:
    """Write every step of a scenario below `directory`, one directory per step.

    The manual entries of the scenario are written next to the steps as
    `manual-entries.toml`, for the configuration of a real host.
    """
    paths = []
    for step in scenario.steps:
        path = directory / step.name
        write(documents_of(scenario, step), path)
        paths.append(path)
    if scenario.devices:
        entries = "".join(
            f'[[discovery.device]]\nname = "{name}"\ntype = "{kind}"\n\n'
            for name, kind in scenario.devices
        )
        (directory / "manual-entries.toml").write_text(entries, encoding="utf-8")
    return paths


def prerequisites(scenario: Scenario) -> list[str]:
    """Return what a real host needs besides the steps to show the scenario.

    The test frame writes the SCSI hosts and SCSI generic nodes into a
    temporary sysfs and the manual entries into the configuration; a real
    host brings the first two itself, or does not show that part.
    """
    notes = []
    first = documents_of(scenario, scenario.steps[0]).get("lsblk.json")
    if first is not None and first != load(scenario.base).get("lsblk.json"):
        notes.append(
            "block devices as in the lsblk.json of the steps, which only the test frame"
            " replays; a real host answers lsblk itself"
        )
    if scenario.devices:
        notes.append("the manual entries of manual-entries.toml in the configuration")
    if scenario.scsi_hosts:
        hosts = ", ".join(
            f"host{number} {driver}" for number, driver in scenario.scsi_hosts.items()
        )
        notes.append(f"the SCSI hosts {hosts} in sysfs")
    if scenario.sg_nodes:
        nodes = ", ".join(f"sg{node} on host{host}" for node, host in scenario.sg_nodes.items())
        notes.append(f"the SCSI generic nodes {nodes}")
    return notes


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the steps of a scenario.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the scenarios and their steps")
    builder = commands.add_parser("build", help="write the steps of one scenario")
    builder.add_argument("scenario", choices=sorted(SCENARIOS))
    builder.add_argument("directory", type=Path)
    arguments = parser.parse_args(argv)

    if arguments.command == "list":
        for scenario in SCENARIOS.values():
            print(f"{scenario.name}: {scenario.description}")
            for note in prerequisites(scenario):
                print(f"  needs {note}")
            for step in scenario.steps:
                print(f"  {step.name:<16} {step.description}")
        return 0
    scenario = SCENARIOS[arguments.scenario]
    for path in build(scenario, arguments.directory):
        print(path)
    for note in prerequisites(scenario):
        print(f"needs {note}", file=sys.stderr)
    return 0


def _attribute_table(document: dict[str, object]) -> list[dict[str, object]]:
    attributes = document.get("ata_smart_attributes")
    assert isinstance(attributes, dict)
    table = attributes.get("table")
    assert isinstance(table, list)
    return table


def _place(document: dict[str, object], name: str, device_type: str) -> None:
    """Make a drive output one of a drive reached through `name` with `device_type`.

    The call names `device_type`; the device fields are what smartctl writes
    for it (`_written_type`). The recording entry and the scan name the type
    of the call, which is what the fake smartctl answers by.
    """
    device = _device_of(document)
    device["name"] = name
    device["type"], device["info_name"] = _written_type(name, device_type, device.get("protocol"))
    smartctl = document.get("smartctl")
    assert isinstance(smartctl, dict)
    smartctl["argv"] = ["smartctl", "--json=c", "--xall", f"--device={device_type}", name]


def _info_name(name: str, device_type: str) -> str:
    """Return the name smartctl shows for a device.

    For MegaRAID as in the Telegraf recording; for the other controllers as
    the constructors of their devices in os_linux.cpp of smartmontools 7.5
    write it. A number the type leaves out, the enclosure of `areca,N` and the
    port of `hpt,L/M`, is 1 here.
    """
    base, _, numbers = device_type.rpartition("+")[2].partition(",")
    parts = [int(part) for part in numbers.replace("/", ",").split(",") if part.isdigit()]
    padded = [*parts, 1, 1, 1]
    names = {
        "megaraid": f"megaraid_disk_{padded[0]:02d}",
        "cciss": f"cciss_disk_{padded[0]:02d}",
        "3ware": f"3ware_disk_{padded[0]:02d}",
        "areca": f"areca_disk#{padded[0]:02d}_enc#{padded[1]:02d}",
        "aacraid": f"aacraid_disk_{padded[0]:02d}_{padded[1]:02d}_{padded[2]}",
        "hpt": "hpt_disk_" + "/".join(str(part) for part in padded[:3]),
        "sssraid": f"sssraid_disk_{padded[0]:02d}_{padded[1]:02d}",
    }
    behind = names.get(base)
    text = f"{name} [{behind}]" if behind else name
    return text + (" [SAT]" if device_type.startswith("sat") else "")


def _written_type(name: str, device_type: str, protocol: object) -> tuple[str, str]:
    """Return the type and `info_name` that smartctl 7.5 writes for a read.

    `3ware`, `areca` and `hpt` keep the name of their device class, without
    the numbers. `cciss`, `aacraid` and `sssraid` are read through an implicit
    `sat,auto`, which writes `sat` and the suffix ` [SAT]` for a SATA drive,
    and keeps the type of the device class with ` [SCSI]` for a SAS drive
    (os_linux.cpp and scsiata.cpp of 7.5). Every other type is written as it
    was called, as in the recordings of MegaRAID.
    """
    info_name = _info_name(name, device_type)
    base = device_type.partition(",")[0]
    if base in {"3ware", "areca", "hpt"}:
        return base, info_name
    if base in {"cciss", "aacraid", "sssraid"}:
        if protocol == "ATA":
            return "sat", f"{info_name} [SAT]"
        return ("cciss" if base == "cciss" else device_type), f"{info_name} [SCSI]"
    return device_type, info_name


def _scan_entry(document: dict[str, object], device_type: str | None = None) -> dict[str, object]:
    device = _device_of(document)
    entry: dict[str, object] = {
        key: device[key] for key in ("name", "info_name", "type", "protocol")
    }
    if device_type is not None:
        entry["type"] = device_type
    return entry


def _recording_entry(
    file: str, document: dict[str, object], *, exit_status: int, device_type: str | None = None
) -> dict[str, object]:
    device = _device_of(document)
    return {
        "file": file,
        "device": device["name"],
        "type": device_type or device["type"],
        "protocol": device["protocol"],
        "exit_status": exit_status,
    }


def _device_of(document: dict[str, object]) -> dict[str, str]:
    device = document.get("device")
    assert isinstance(device, dict)
    return device


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
