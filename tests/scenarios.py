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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
#: follow the acceptance steps of milestone M4 in ROADMAP.md, those of the
#: MegaRAID scenarios the deliverables of milestone M6.
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
            name="megaraid-jbod",
            base=MEGARAID_BASE,
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
    """Write every step of a scenario below `directory`, one directory per step."""
    paths = []
    for step in scenario.steps:
        path = directory / step.name
        write(documents_of(scenario, step), path)
        paths.append(path)
    return paths


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
            for step in scenario.steps:
                print(f"  {step.name:<16} {step.description}")
        return 0
    for path in build(SCENARIOS[arguments.scenario], arguments.directory):
        print(path)
    return 0


def _attribute_table(document: dict[str, object]) -> list[dict[str, object]]:
    attributes = document.get("ata_smart_attributes")
    assert isinstance(attributes, dict)
    table = attributes.get("table")
    assert isinstance(table, list)
    return table


def _place(document: dict[str, object], name: str, device_type: str) -> None:
    """Make a drive output one of a drive reached through `name` with `device_type`."""
    device = _device_of(document)
    device["name"] = name
    device["type"] = device_type
    device["info_name"] = _info_name(name, device_type)
    smartctl = document.get("smartctl")
    assert isinstance(smartctl, dict)
    smartctl["argv"] = ["smartctl", "--json=c", "--xall", f"--device={device_type}", name]


def _info_name(name: str, device_type: str) -> str:
    """Return the name smartctl shows for a device, as in the Telegraf recording."""
    number = device_type.rpartition(",")[2]
    behind = f" [megaraid_disk_{int(number):02d}]" if "megaraid" in device_type else ""
    return f"{name}{behind}" + (" [SAT]" if device_type.startswith("sat") else "")


def _scan_entry(document: dict[str, object]) -> dict[str, object]:
    device = _device_of(document)
    return {key: device[key] for key in ("name", "info_name", "type", "protocol")}


def _recording_entry(
    file: str, document: dict[str, object], *, exit_status: int
) -> dict[str, object]:
    device = _device_of(document)
    return {
        "file": file,
        "device": device["name"],
        "type": device["type"],
        "protocol": device["protocol"],
        "exit_status": exit_status,
    }


def _device_of(document: dict[str, object]) -> dict[str, str]:
    device = document.get("device")
    assert isinstance(device, dict)
    return device


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
