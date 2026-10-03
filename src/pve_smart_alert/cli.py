# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command-line interface of PVE SMART Alert.

The commands of later milestones (`check`, `status`, `scan`, `doctor`,
`test-notification`, `dump-fixture`, `config`) are added here as they arrive.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from pve_smart_alert import __version__

PROGRAM = "pve-smart-alert"
DESCRIPTION = "SMART drive alerts for Proxmox VE"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the program."""
    parser = argparse.ArgumentParser(prog=PROGRAM, description=DESCRIPTION)
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM} {__version__}",
        help="show the version and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the program and return its exit status."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
