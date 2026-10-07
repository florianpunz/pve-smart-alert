#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn archives of scripts/collect-node-data.sh into anonymized fixtures.

Fixtures are written by this script only, never by hand (ADR 0023). For each
archive it reads the device scan and the drive outputs of smartctl, numbers
the identifying values in the order of the scan, replaces them with
placeholders, checks every output for real values that are left, and only
then writes a directory with `scan.json`, one file per device, `lsblk.json`
when the archive has it, and `recording.json`:

    tests/fixtures/smartctl/<controller>/<prefix>-<node>/

The archives are read where they are and never copied or unpacked: they
contain real serial numbers and stay out of the repository (ADR 0016).

Usage:
    scripts/make_fixtures.py --output tests/fixtures/smartctl/direct \\
        --prefix test-cluster --origin "Test cluster of the maintainer" ARCHIVE...

Exit status: 0 when every archive was written, 1 when one could not be
anonymized safely, in which case nothing of that archive is written.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

from pve_smart_alert.anonymize import AnonymizationError, Anonymizer

DEFAULT_LICENSE: Final = "AGPL-3.0-or-later"
COLLECTED_WITH: Final = "scripts/collect-node-data.sh"
# The command scripts/collect-node-data.sh records the block devices with.
LSBLK_COMMAND: Final = "lsblk -J -O"
ANONYMIZED_WITH: Final = "scripts/make_fixtures.py (ADR 0023)"


@dataclass
class Recording:
    """What one archive holds, read but not anonymized yet."""

    info: dict[str, str]
    scan: dict[str, object]
    scan_exit: int | None
    drives: dict[str, dict[str, object]] = field(default_factory=dict)
    exits: dict[str, int | None] = field(default_factory=dict)
    lsblk: object = None
    lsblk_exit: int | None = None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("archives", nargs="+", type=Path, metavar="ARCHIVE")
    parser.add_argument("--output", type=Path, required=True, help="the controller directory")
    parser.add_argument("--prefix", default="recording", help="the name before the node")
    parser.add_argument("--origin", required=True, help="where the recordings come from")
    parser.add_argument("--license", default=DEFAULT_LICENSE, help="SPDX license of the data")
    arguments = parser.parse_args(argv)

    status = 0
    for archive in arguments.archives:
        try:
            recording = read_archive(archive)
            files = anonymize(recording, origin=arguments.origin, license_id=arguments.license)
        except (AnonymizationError, KeyError, ValueError, OSError) as error:
            print(f"{archive.name}: not written: {error}", file=sys.stderr)
            status = 1
            continue
        directory = arguments.output / f"{arguments.prefix}-{recording.info['node']}"
        write(directory, files)
        print(f"{archive.name}: written to {directory}")
    return status


def read_archive(path: Path) -> Recording:
    """Read the scan, the drive outputs and their exit statuses of one archive."""
    with tarfile.open(path, "r:gz") as archive:
        contents = {
            PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix(): _read(archive, member)
            for member in archive.getmembers()
            if member.isfile()
        }

    info = dict(line.split(": ", 1) for line in contents["info.txt"].splitlines() if ": " in line)
    recording = Recording(
        info=info,
        scan=json.loads(contents["scan.json"]),
        scan_exit=_exit(contents.get("scan.json.exit")),
    )
    if "lsblk.json" in contents:
        recording.lsblk = json.loads(contents["lsblk.json"])
        recording.lsblk_exit = _exit(contents.get("lsblk.json.exit"))
    for name, text in sorted(contents.items()):
        if name.startswith("smart/") and name.endswith(".json"):
            device = name.removeprefix("smart/").removesuffix(".json")
            recording.drives[device] = json.loads(text)
            recording.exits[device] = _exit(contents.get(f"{name}.exit"))
    return recording


def anonymize(recording: Recording, *, origin: str, license_id: str) -> dict[str, object]:
    """Return the files of the fixture, keyed by file name, all checked."""
    anonymizer = Anonymizer()
    order = _scan_order(recording)
    for device in order:
        anonymizer.learn(recording.drives[device])

    # After the drives of the scan, so that drives only lsblk shows come last.
    if recording.lsblk is not None:
        anonymizer.learn_lsblk(recording.lsblk)

    files: dict[str, object] = {"scan.json": anonymizer.document(recording.scan)}
    for device in order:
        files[f"{device}.json"] = anonymizer.drive(recording.drives[device])
    if recording.lsblk is not None:
        files["lsblk.json"] = anonymizer.lsblk(recording.lsblk)
    files["recording.json"] = _metadata(recording, order, origin=origin, license_id=license_id)

    for name, document in files.items():
        anonymizer.check(document, name=name)
    return files


def write(directory: Path, files: Mapping[str, object]) -> None:
    """Write the files of one fixture, indented, each with a final newline."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, document in files.items():
        text = json.dumps(document, indent=2, ensure_ascii=False)
        (directory / name).write_text(text + "\n", encoding="utf-8")


def _scan_order(recording: Recording) -> list[str]:
    """Return the devices in the order of the scan, then the others by name."""
    devices = recording.scan.get("devices")
    scanned: list[str] = []
    if isinstance(devices, list):
        for entry in devices:
            name = entry.get("name") if isinstance(entry, dict) else None
            device = PurePosixPath(name).name if isinstance(name, str) else None
            if device in recording.drives and device not in scanned:
                scanned.append(device)
    return scanned + sorted(set(recording.drives) - set(scanned))


def _metadata(
    recording: Recording, order: Sequence[str], *, origin: str, license_id: str
) -> dict[str, object]:
    """Return the content of `recording.json` (ADR 0016, ADR 0023)."""
    files: list[dict[str, object]] = [
        {
            "file": "scan.json",
            "command": _command(recording.scan),
            "exit_status": recording.scan_exit,
        }
    ]
    for device in order:
        drive = recording.drives[device]
        access = drive.get("device")
        access = access if isinstance(access, dict) else {}
        files.append(
            {
                "file": f"{device}.json",
                "device": access.get("name"),
                "type": access.get("type"),
                "protocol": access.get("protocol"),
                "class": _drive_class(drive),
                "model": drive.get("model_name"),
                "command": _command(drive),
                "exit_status": recording.exits.get(device),
            }
        )
    if recording.lsblk is not None:
        files.append(
            {"file": "lsblk.json", "command": LSBLK_COMMAND, "exit_status": recording.lsblk_exit}
        )
    return {
        "origin": origin,
        "license": license_id,
        "node": recording.info["node"],
        "collected": recording.info.get("collected"),
        "collected_with": COLLECTED_WITH,
        "anonymized_with": ANONYMIZED_WITH,
        "smartmontools": _version(recording.scan),
        "controller": "none, directly attached",
        "files": files,
    }


def _drive_class(drive: Mapping[str, object]) -> str:
    """Return the class of the check catalog: nvme, or ssd and hdd by rotation rate."""
    access = drive.get("device")
    if isinstance(access, dict) and access.get("protocol") == "NVMe":
        return "nvme"
    # An unknown rotation rate counts as a hard disk (docs/check-catalog.md).
    return "ssd" if drive.get("rotation_rate") == 0 else "hdd"


def _command(document: Mapping[str, object]) -> str | None:
    """Return the command line that produced an output, as smartctl reports it."""
    smartctl = document.get("smartctl")
    argv = smartctl.get("argv") if isinstance(smartctl, dict) else None
    if isinstance(argv, list) and all(isinstance(argument, str) for argument in argv):
        return " ".join(argv)
    return None


def _version(document: Mapping[str, object]) -> str | None:
    """Return the version of smartmontools that wrote an output."""
    smartctl = document.get("smartctl")
    version = smartctl.get("version") if isinstance(smartctl, dict) else None
    if isinstance(version, list):
        return ".".join(str(part) for part in version)
    return None


def _read(archive: tarfile.TarFile, member: tarfile.TarInfo) -> str:
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"cannot read {member.name}")
    with stream:
        return stream.read().decode("utf-8")


def _exit(text: str | None) -> int | None:
    return None if text is None or not text.strip() else int(text.strip())


if __name__ == "__main__":
    sys.exit(main())
