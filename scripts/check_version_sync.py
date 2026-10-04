#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check that the version of the program is the version of the package.

The version of the program lives in ``src/pve_smart_alert/__init__.py``: it is
what ``--version`` prints and what the package metadata reads. The version of
the Debian package lives in the newest entry of ``debian/changelog``. Since the
package ships the program as it is, both name the same release, and a
difference means that one of the two was forgotten (ADR 0013).

Usage:
    scripts/check_version_sync.py [--root PATH]

Exit status: 0 when both versions are the same, 1 when they are not.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parent.parent

VERSION_MODULE: Final = Path("src/pve_smart_alert/__init__.py")
CHANGELOG: Final = Path("debian/changelog")

VERSION_PATTERN: Final = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
# The first line of a changelog entry, as in
# "pve-smart-alert (0.1.0) unstable; urgency=medium".
CHANGELOG_PATTERN: Final = re.compile(r"^pve-smart-alert \(([^)]+)\)", re.MULTILINE)


class VersionMissingError(Exception):
    """A file that should name a version does not name one."""


def read_version(path: Path, pattern: re.Pattern[str], what: str) -> str:
    """Return the version a file names, or raise ``VersionMissingError``."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as failure:
        reason = failure.strerror or failure
        raise VersionMissingError(f"{path} could not be read: {reason}") from failure

    match = pattern.search(content)
    if match is None:
        raise VersionMissingError(f"{path} does not name {what}")
    return match.group(1)


def check_version_sync(root: Path) -> list[str]:
    """Return the problems found. No problem means the versions agree."""
    try:
        program = read_version(root / VERSION_MODULE, VERSION_PATTERN, "__version__")
        package = read_version(root / CHANGELOG, CHANGELOG_PATTERN, "a changelog entry")
    except VersionMissingError as problem:
        return [str(problem)]

    if program != package:
        return [
            f"{VERSION_MODULE} has {program} and {CHANGELOG} has {package}:"
            " the package ships this version of the program (ADR 0013)"
        ]
    return []


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository to check (default: the repository this script is in)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return its exit status."""
    arguments = build_parser().parse_args(argv)
    root: Path = arguments.root.resolve()

    problems = check_version_sync(root)
    for problem in problems:
        print(problem)

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
