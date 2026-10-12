#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scenarios for the fake smartctl: a host whose drives change step by step (ADR 0016).

A scenario is a base recording of `fixtures/smartctl/` and a sequence of
steps. Each step is a whole recording directory, derived from the base by
changing values, adding copies of a drive or removing one, that the fake
smartctl replays when FAKE_SMARTCTL_RECORDING names it. The steps are
derived, not recorded; the base recordings are listed in
`fixtures/SOURCES.md`.

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

RECORDINGS: Final = Path(__file__).resolve().parent / "fixtures" / "smartctl" / "direct"

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


#: The scenarios, by name. The steps of `pending-sectors` and `five-hot`
#: follow the acceptance steps of milestone M4 in ROADMAP.md.
SCENARIOS: Final = {
    scenario.name: scenario
    for scenario in (
        Scenario(
            name="pending-sectors",
            base="standalone-pve1",
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
            base="standalone-pve1",
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


def _device_of(document: dict[str, object]) -> dict[str, str]:
    device = document.get("device")
    assert isinstance(device, dict)
    return device


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
