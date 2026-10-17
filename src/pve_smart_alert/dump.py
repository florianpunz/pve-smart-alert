# SPDX-License-Identifier: AGPL-3.0-or-later
"""`pve-smart-alert dump-fixture`: the drive data of this host, anonymized (FR-604).

It runs what the tool runs, the device scan, lsblk and the call of smartctl
for each selected drive, and keeps the answers as they are, also those of
drives that sleep or cannot be read: their messages are what a recording of
other hardware is for (ADR 0016). The answers are anonymized as ADR 0023
lays down and written as one archive in the layout of the fixtures, so that
it can be attached to an issue and, after a review, added to the tests. When
a real value is left in any file, nothing is written (NFR-14).
"""

from __future__ import annotations

import io
import json
import re
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final

from pve_smart_alert import __version__
from pve_smart_alert.collect import drive_command
from pve_smart_alert.config import Config
from pve_smart_alert.discovery.enrichment import (
    HOST,
    LSBLK_TIMEOUT_SECONDS,
    HostPaths,
    lsblk_command,
)
from pve_smart_alert.discovery.sources import Candidate, manual_candidates, parse_scan, scan_command
from pve_smart_alert.process import ProcessRunner, run_with_timeout
from pve_smart_alert.recording import Recording, anonymize, serialize

# The license under which a recording comes into the project, like every
# contribution (CONTRIBUTING.md, ADR 0015).
LICENSE: Final = "AGPL-3.0-or-later"
ANONYMIZED_WITH: Final = "pve-smart-alert dump-fixture (ADR 0023)"

_UNSAFE: Final = re.compile(r"[^a-z0-9_-]+")


class DumpError(Exception):
    """A dump that cannot be made: no scan, or a device that is not known."""


@dataclass(frozen=True)
class Dump:
    """What `dump_fixture` wrote."""

    archive: Path
    devices: tuple[str, ...]


def dump_fixture(
    config: Config,
    *,
    devices: Sequence[str] | None,
    output: Path,
    node: str,
    now: datetime,
    runner: ProcessRunner = run_with_timeout,
    paths: HostPaths = HOST,
) -> Dump:
    """Record the scan, lsblk and the selected drives, anonymized, as an archive.

    `devices` names the drives to record, `None` means all of them. Raises
    `DumpError`, or `AnonymizationError` when a real value would be left.
    """
    settings = config.smartctl
    scan_result = runner(scan_command(settings), timeout=settings.timeout_seconds)
    scan = parse_scan(scan_result.stdout)
    if scan.error is not None:
        raise DumpError(scan.error)

    candidates = _selected(
        list(scan.candidates) + list(manual_candidates(config.discovery.devices)), devices
    )
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    recording = Recording(
        node=node,
        collected=stamp,
        collected_with=f"pve-smart-alert dump-fixture {__version__}",
        scan=json.loads(scan_result.stdout),
        scan_exit=scan_result.returncode,
    )
    for candidate in candidates:
        stem = _stem(candidate, recording)
        result = runner(
            drive_command(
                candidate.name, candidate.type, settings=settings, protocol=candidate.protocol
            ),
            timeout=settings.timeout_seconds,
        )
        document = _json_object(result.stdout)
        if document is not None:
            recording.drives[stem] = document
            recording.exits[stem] = result.returncode
            recording.calls[stem] = (candidate.name, candidate.type)

    lsblk = runner(lsblk_command(paths), timeout=LSBLK_TIMEOUT_SECONDS)
    recording.lsblk = _json_object(lsblk.stdout)
    if recording.lsblk is not None:
        recording.lsblk_exit = lsblk.returncode
        recording.lsblk_command = " ".join(["lsblk", *lsblk_command(paths)[1:]])

    files = anonymize(
        recording,
        origin=f"Recorded by pve-smart-alert dump-fixture {__version__}",
        license_id=LICENSE,
        anonymized_with=ANONYMIZED_WITH,
    )
    name = f"pve-smart-alert-fixture-{node}-{stamp}"
    archive = output / f"{name}.tar.gz"
    _write_archive(archive, name, files, mtime=int(now.timestamp()))
    return Dump(archive=archive, devices=tuple(candidate.name for candidate in candidates))


def _selected(candidates: Sequence[Candidate], devices: Sequence[str] | None) -> list[Candidate]:
    """Return the devices to record, each name and type once."""
    unique: dict[tuple[str, str], Candidate] = {}
    for candidate in candidates:
        if candidate.valid:
            unique.setdefault((candidate.name, candidate.type), candidate)
    if devices is None:
        return list(unique.values())

    selected = [candidate for candidate in unique.values() if candidate.name in devices]
    unknown = sorted(set(devices) - {candidate.name for candidate in selected})
    if unknown:
        raise DumpError("not found by the scan or as a manual device: " + ", ".join(unknown))
    return selected


def _stem(candidate: Candidate, recording: Recording) -> str:
    """Return the file name of a drive output: its device, with its type when taken."""
    stem = PurePosixPath(candidate.name).name
    if stem in recording.drives:
        stem = f"{stem}-{_UNSAFE.sub('_', candidate.type)}"
    return stem


def _json_object(text: str) -> dict[str, object] | None:
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return None
    return document if isinstance(document, dict) else None


def _write_archive(path: Path, name: str, files: dict[str, object], *, mtime: int) -> None:
    """Write the files below one directory into a compressed archive."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        for file, document in files.items():
            data = serialize(document).encode("utf-8")
            member = tarfile.TarInfo(f"{name}/{file}")
            member.size = len(data)
            member.mode = 0o644
            member.mtime = mtime
            archive.addfile(member, io.BytesIO(data))
