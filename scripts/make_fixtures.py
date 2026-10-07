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
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Final

from pve_smart_alert.anonymize import AnonymizationError
from pve_smart_alert.recording import Recording, anonymize, write_directory

DEFAULT_LICENSE: Final = "AGPL-3.0-or-later"
COLLECTED_WITH: Final = "scripts/collect-node-data.sh"
# The command scripts/collect-node-data.sh records the block devices with.
LSBLK_COMMAND: Final = "lsblk -J -O"
# The test cluster has no controller between drives and host (Research 06).
CONTROLLER: Final = "none, directly attached"
ANONYMIZED_WITH: Final = "scripts/make_fixtures.py (ADR 0023)"


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
            files = anonymize(
                recording,
                origin=arguments.origin,
                license_id=arguments.license,
                anonymized_with=ANONYMIZED_WITH,
            )
        except (AnonymizationError, KeyError, ValueError, OSError) as error:
            print(f"{archive.name}: not written: {error}", file=sys.stderr)
            status = 1
            continue
        directory = arguments.output / f"{arguments.prefix}-{recording.node}"
        write_directory(directory, files)
        print(f"{archive.name}: written to {directory}")
    return status


def read_archive(path: Path) -> Recording:
    """Read the scan, the drive outputs, lsblk and their exit statuses of one archive."""
    with tarfile.open(path, "r:gz") as archive:
        contents = {
            PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix(): _read(archive, member)
            for member in archive.getmembers()
            if member.isfile()
        }

    info = dict(line.split(": ", 1) for line in contents["info.txt"].splitlines() if ": " in line)
    recording = Recording(
        node=info["node"],
        collected=info.get("collected"),
        collected_with=COLLECTED_WITH,
        scan=json.loads(contents["scan.json"]),
        scan_exit=_exit(contents.get("scan.json.exit")),
        controller=CONTROLLER,
    )
    if "lsblk.json" in contents:
        recording.lsblk = json.loads(contents["lsblk.json"])
        recording.lsblk_exit = _exit(contents.get("lsblk.json.exit"))
        recording.lsblk_command = LSBLK_COMMAND
    for name, text in sorted(contents.items()):
        if name.startswith("smart/") and name.endswith(".json"):
            stem = name.removeprefix("smart/").removesuffix(".json")
            recording.drives[stem] = json.loads(text)
            recording.exits[stem] = _exit(contents.get(f"{name}.exit"))
    return recording


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
