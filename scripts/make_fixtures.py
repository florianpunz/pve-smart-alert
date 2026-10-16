#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn recordings into anonymized fixtures: archives of the collection
script, or the smartctl test data of other projects.

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

The subcommand `import` makes one fixture of JSON files that another project
publishes as its test data (ADR 0026). The files are read where they are, a
device scan only if the source has one, and the repository, the commit, the
path and the copyright of the source are written to `recording.json`:

    scripts/make_fixtures.py import \\
        --output tests/fixtures/smartctl/direct/libblockdev-hgst-husmr3280ass200 \\
        --origin "..." --license LGPL-2.1-or-later --repository URL \\
        --commit SHA --copyright "..." \\
        --license-file tests/fixtures/licenses/libblockdev-LGPL-2.1.txt \\
        --drive sdc=PATH_IN_REPOSITORY:LOCAL_FILE

Exit status: 0 when every fixture was written, 1 when one could not be
anonymized safely, in which case nothing of it is written.
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
IMPORTED_WITH: Final = "scripts/make_fixtures.py import (ADR 0023, ADR 0026)"
# The licenses whose data can be part of a project under AGPL-3.0-or-later
# (ADR 0026). Anything else is refused.
COMPATIBLE_LICENSES: Final = frozenset(
    {
        "AGPL-3.0-or-later",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-or-later",
        "LGPL-3.0-or-later",
        "MIT",
    }
)


def main(argv: Sequence[str] | None = None) -> int:
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    if arguments_list[:1] == ["import"]:
        return import_main(arguments_list[1:])
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


def import_main(argv: Sequence[str]) -> int:
    """Make one fixture of the test data of another project (ADR 0026)."""
    parser = argparse.ArgumentParser(prog="make_fixtures.py import")
    parser.add_argument("--output", type=Path, required=True, help="the recording directory")
    parser.add_argument("--origin", required=True, help="what the recording is and shows")
    parser.add_argument("--license", required=True, help="SPDX license of the source")
    parser.add_argument("--repository", required=True, help="URL of the source repository")
    parser.add_argument("--commit", required=True, help="the commit the files were read at")
    parser.add_argument("--copyright", required=True, help="the copyright line of the source")
    parser.add_argument(
        "--license-file",
        type=Path,
        required=True,
        help="the license text of the source as kept below tests/fixtures/licenses",
    )
    parser.add_argument("--controller", default=CONTROLLER, help="what the drives are behind")
    parser.add_argument("--changes", help="what the source changed in its files, if anything")
    parser.add_argument("--scan", metavar="PATH:FILE", help="the device scan, if there is one")
    parser.add_argument(
        "--drive",
        action="append",
        default=[],
        metavar="STEM=PATH:FILE",
        help="one drive output: its file name in the fixture, its path in the source, the file",
    )
    arguments = parser.parse_args(argv)

    if arguments.license not in COMPATIBLE_LICENSES:
        print(f"not written: {arguments.license} is not a compatible license", file=sys.stderr)
        return 1
    if not arguments.license_file.is_file():
        print(f"not written: no license text at {arguments.license_file}", file=sys.stderr)
        return 1
    try:
        recording = read_sources(arguments)
        files = anonymize(
            recording,
            origin=arguments.origin,
            license_id=arguments.license,
            anonymized_with=IMPORTED_WITH,
        )
    except (AnonymizationError, ValueError, OSError) as error:
        print(f"{arguments.output.name}: not written: {error}", file=sys.stderr)
        return 1
    write_directory(arguments.output, files)
    print(f"written to {arguments.output}")
    return 0


def read_sources(arguments: argparse.Namespace) -> Recording:
    """Read the files of an import and describe where they come from."""
    paths: dict[str, str] = {}
    scan = None
    if arguments.scan is not None:
        path, local = _source(arguments.scan)
        scan = json.loads(local.read_text(encoding="utf-8"))
        paths["scan.json"] = path
    recording = Recording(
        node="unknown",
        collected=None,
        collected_with=f"the test data of {arguments.repository}",
        scan=scan,
        scan_exit=_json_exit(scan),
        controller=arguments.controller,
    )
    for entry in arguments.drive:
        stem, separator, rest = entry.partition("=")
        if not separator or not stem:
            raise ValueError(f"--drive {entry}: expected STEM=PATH:FILE")
        path, local = _source(rest)
        recording.drives[stem] = json.loads(local.read_text(encoding="utf-8"))
        recording.exits[stem] = _json_exit(recording.drives[stem])
        paths[f"{stem}.json"] = path
    if scan is None and not recording.drives:
        raise ValueError("neither a scan nor a drive given")
    source: dict[str, object] = {
        "repository": arguments.repository,
        "commit": arguments.commit,
        "copyright": arguments.copyright,
        "license_file": arguments.license_file.as_posix(),
        "paths": paths,
    }
    if arguments.changes:
        source["changes"] = arguments.changes
    recording.source = source
    return recording


def _source(text: str) -> tuple[str, Path]:
    """Split PATH:FILE into the path in the source repository and the local file."""
    path, separator, local = text.partition(":")
    if not separator or not path or not local:
        raise ValueError(f"{text}: expected PATH:FILE")
    return path, Path(local)


def _json_exit(document: object) -> int | None:
    """Return the exit status that smartctl wrote into its own output, if it did."""
    smartctl = document.get("smartctl") if isinstance(document, dict) else None
    status = smartctl.get("exit_status") if isinstance(smartctl, dict) else None
    return status if isinstance(status, int) else None


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
