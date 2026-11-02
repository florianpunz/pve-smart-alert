# SPDX-License-Identifier: AGPL-3.0-or-later
"""An anonymized recording of one host (ADR 0016, ADR 0023).

A recording is what a host answered: the device scan, one drive output per
device and the block devices of lsblk. `anonymize` turns it into the files of
a fixture: the identifiers numbered in the order of the scan, every file
checked for real values, and `recording.json` describing where each file
comes from. `scripts/make_fixtures.py` makes fixtures of archives of the
collection script and of the test data of other projects with it, and
`pve-smart-alert dump-fixture` (FR-604) the archive a user can attach to an
issue.

A recording taken from another project may lack the device scan, or consist of
the scan alone. Nothing missing is made up: such a fixture simply has no
`scan.json`, or no drive files (ADR 0026).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pve_smart_alert.anonymize import Anonymizer


@dataclass
class Recording:
    """What one host answered, before anonymization.

    `drives` are the drive outputs by the name of their file without
    `.json`, `exits` their exit statuses, and `calls` the device name and
    type each was read with, where they are known. `scan` is `None` when the
    source has no device scan. `source` says where a recording of another project
    was taken from: repository, commit, path and copyright (ADR 0026).
    """

    node: str
    collected: str | None
    collected_with: str
    scan: Mapping[str, object] | None
    scan_exit: int | None
    drives: dict[str, Mapping[str, object]] = field(default_factory=dict)
    exits: dict[str, int | None] = field(default_factory=dict)
    calls: dict[str, tuple[str, str]] = field(default_factory=dict)
    lsblk: object = None
    lsblk_exit: int | None = None
    lsblk_command: str | None = None
    controller: str | None = None
    source: Mapping[str, object] | None = None


def anonymize(
    recording: Recording, *, origin: str, license_id: str, anonymized_with: str
) -> dict[str, object]:
    """Return the files of the fixture, by file name, each checked for real values.

    Raises `AnonymizationError` when a real value is left in any of them; then
    nothing may be written (ADR 0023).
    """
    anonymizer = Anonymizer()
    order = scan_order(recording)
    for stem in order:
        anonymizer.learn(recording.drives[stem])
    # After the drives of the scan, so that drives only lsblk shows come last.
    if recording.lsblk is not None:
        anonymizer.learn_lsblk(recording.lsblk)
    # A device name that is not a kernel name can hold a serial number: it
    # is replaced before any file name or text is built from it (ADR 0023).
    filenames = _file_names(recording, order, anonymizer)

    files: dict[str, object] = {}
    if recording.scan is not None:
        files["scan.json"] = anonymizer.document(recording.scan)
    for stem in order:
        files[f"{filenames[stem]}.json"] = anonymizer.drive(recording.drives[stem])
    if recording.lsblk is not None:
        files["lsblk.json"] = anonymizer.lsblk(recording.lsblk)
    metadata = _metadata(
        recording,
        order,
        filenames,
        origin=origin,
        license_id=license_id,
        anonymized_with=anonymized_with,
    )
    files["recording.json"] = anonymizer.document(metadata)

    for name, document in files.items():
        anonymizer.check_name(name)
        anonymizer.check(document, name=name)
    return files


def serialize(document: object) -> str:
    """Return a file of a fixture: indented JSON with a final newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_directory(directory: Path, files: Mapping[str, object]) -> None:
    """Write the files of one fixture into a directory."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, document in files.items():
        (directory / name).write_text(serialize(document), encoding="utf-8")


def scan_order(recording: Recording) -> list[str]:
    """Return the drive files in the order of the scan, then the others by name."""
    devices = recording.scan.get("devices") if recording.scan is not None else None
    scanned: list[str] = []
    if isinstance(devices, list):
        for entry in devices:
            name = entry.get("name") if isinstance(entry, dict) else None
            for stem, drive in recording.drives.items():
                if stem not in scanned and _device_name(drive) == name:
                    scanned.append(stem)
    return scanned + sorted(set(recording.drives) - set(scanned))


def drive_class(drive: Mapping[str, object]) -> str:
    """Return the class of the check catalog: nvme, or ssd and hdd by rotation rate."""
    access = drive.get("device")
    if isinstance(access, dict) and access.get("protocol") == "NVMe":
        return "nvme"
    # An unknown rotation rate counts as a hard disk (docs/check-catalog.md).
    return "ssd" if drive.get("rotation_rate") == 0 else "hdd"


def _file_names(
    recording: Recording, order: Sequence[str], anonymizer: Anonymizer
) -> dict[str, str]:
    """Return the file name of each drive output, one name per drive.

    The name comes from the anonymized device a drive was read through.
    Several drives can share that device, such as the drives behind a
    MegaRAID controller, which are all read through one device with a
    different smartctl type: the second and every later one gets a number, so
    that one output never overwrites another (ADR 0023).
    """
    names: dict[str, str] = {}
    used: set[str] = set()
    for stem in order:
        base = _file_stem(recording, stem, anonymizer)
        name = base
        number = 2
        while name in used:
            name = f"{base}-{number}"
            number += 1
        used.add(name)
        names[stem] = name
    return names


def _file_stem(recording: Recording, stem: str, anonymizer: Anonymizer) -> str:
    """Return the file name of a drive output: its device name without the path.

    A device name that is not a kernel name is replaced by the anonymizer
    first, so that a `by-id` link cannot put a serial number into a file
    name (ADR 0023).
    """
    name = _recorded_name(recording, stem)
    if isinstance(name, str) and name:
        return PurePosixPath(anonymizer.learn_device(name)).name
    return stem


def _recorded_name(recording: Recording, stem: str) -> object:
    """Return the device name a drive output was read through, if it is known."""
    call = recording.calls.get(stem)
    if call is not None:
        return call[0]
    return _device_name(recording.drives[stem])


def _metadata(
    recording: Recording,
    order: Sequence[str],
    filenames: Mapping[str, str],
    *,
    origin: str,
    license_id: str,
    anonymized_with: str,
) -> dict[str, object]:
    """Return the content of `recording.json`."""
    files: list[dict[str, object]] = []
    if recording.scan is not None:
        files.append(
            {
                "file": "scan.json",
                "command": _command(recording.scan),
                "exit_status": recording.scan_exit,
            }
        )
    for stem in order:
        drive = recording.drives[stem]
        access = drive.get("device")
        access = access if isinstance(access, dict) else {}
        # The type of the call, not the one smartctl writes into the output:
        # for `3ware,N` it writes `3ware`, for a SATA drive read as `cciss,N`
        # `sat`. The fake smartctl answers by the type of the call (ADR 0016).
        name, device_type = recording.calls.get(stem, (access.get("name"), access.get("type")))
        files.append(
            {
                "file": f"{filenames[stem]}.json",
                "device": name,
                "type": device_type,
                "protocol": access.get("protocol"),
                "class": drive_class(drive),
                "model": _model(drive),
                "command": _command(drive),
                "exit_status": recording.exits.get(stem),
            }
        )
    if recording.lsblk is not None:
        files.append(
            {
                "file": "lsblk.json",
                "command": recording.lsblk_command,
                "exit_status": recording.lsblk_exit,
            }
        )
    metadata: dict[str, object] = {
        "origin": origin,
        "license": license_id,
        "node": recording.node,
        "collected": recording.collected,
        "collected_with": recording.collected_with,
        "anonymized_with": anonymized_with,
        "smartmontools": _recorded_version(recording, order),
        "controller": recording.controller,
        "files": files,
    }
    if recording.source is not None:
        metadata["source"] = dict(recording.source)
    return metadata


def _recorded_version(recording: Recording, order: Sequence[str]) -> str | None:
    """Return the version of smartmontools of the scan, or of the first drive without one."""
    for document in [recording.scan, *(recording.drives[stem] for stem in order)]:
        version = _version(document) if document is not None else None
        if version is not None:
            return version
    return None


def _model(drive: Mapping[str, object]) -> object:
    """Return the model name: for SCSI from smartmontools 7.3 on, `scsi_model_name`."""
    model = drive.get("model_name")
    return model if model is not None else drive.get("scsi_model_name")


def _device_name(drive: Mapping[str, object]) -> object:
    access = drive.get("device")
    return access.get("name") if isinstance(access, dict) else None


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
