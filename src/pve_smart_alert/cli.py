# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command-line interface of PVE SMART Alert.

The commands of later milestones (`check`, `status`, `scan`, `config`,
`dump-fixture`) are added here as they arrive.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pve_smart_alert import __version__
from pve_smart_alert.config import ConfigError, NotifySettings, TransportName, load_config
from pve_smart_alert.model import (
    PVE_SEVERITY,
    SEVERITY_FOR_PVE,
    Notification,
    PveSeverity,
    node_name,
)
from pve_smart_alert.render import render_test_notification
from pve_smart_alert.transports import TransportOutcome, build_transport

PROGRAM = "pve-smart-alert"
DESCRIPTION = "SMART drive alerts for Proxmox VE"

# The command ran and the message was delivered, or it was not: the second
# one is a finding of the command, not a failure of the tool (FR-520).
EXIT_OK = 0
EXIT_NOT_DELIVERED = 1
# A usage error and an unusable configuration both end here, the same status
# that the argument parser uses for its own errors.
EXIT_USAGE = 2

SEVERITY_CHOICES = [severity.value for severity in PveSeverity]
TRANSPORT_CHOICES = [transport.value for transport in TransportName]


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the program."""
    parser = argparse.ArgumentParser(prog=PROGRAM, description=DESCRIPTION)
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM} {__version__}",
        help="show the version and exit",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    test_notification = commands.add_parser(
        "test-notification",
        help="send a test notification through the configured transport",
        description=(
            "Send one test notification and report what the notification system did with it."
        ),
    )
    test_notification.add_argument(
        "--severity",
        choices=SEVERITY_CHOICES,
        default=PveSeverity.INFO.value,
        help="severity the notification carries (default: %(default)s)",
    )
    test_notification.add_argument(
        "--transport",
        choices=TRANSPORT_CHOICES,
        default=None,
        help="transport to use instead of the configured one (default: the configuration)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the program and return its exit status."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "test-notification":
        return _test_notification(arguments)

    parser.print_help()
    return EXIT_OK


def _test_notification(arguments: argparse.Namespace) -> int:
    """Send one test notification and report what became of it (FR-520)."""
    try:
        config = load_config()
    except ConfigError as error:
        # An unusable configuration is worth reporting even when this run does
        # not use it: the next run will.
        print(f"{PROGRAM}: {error}", file=sys.stderr)
        return EXIT_USAGE

    settings = config.notify
    if arguments.transport is not None:
        settings = NotifySettings(transport=TransportName(arguments.transport))

    notification = render_test_notification(
        SEVERITY_FOR_PVE[PveSeverity(arguments.severity)], node=node_name()
    )
    outcome = build_transport(settings).send(notification)
    _report(notification, settings, outcome)

    return EXIT_OK if outcome.delivered else EXIT_NOT_DELIVERED


def _report(
    notification: Notification,
    settings: NotifySettings,
    outcome: TransportOutcome,
) -> None:
    """Print what the notification system did with the test notification."""
    print(_labelled("Transport", settings.transport.value))
    print(_labelled("Severity", PVE_SEVERITY[notification.severity].value))
    print(_labelled("Delivered", "yes" if outcome.delivered else "no"))
    if outcome.delivered:
        print(_labelled("Used", outcome.transport.value))
    print(_labelled("Duration", f"{outcome.duration_seconds:.2f} s"))
    if outcome.fallback_reason is not None:
        print(_labelled("Fallback", outcome.fallback_reason))
    if outcome.error is not None:
        print(_labelled("Error", outcome.error))

    print("Log:")
    if outcome.log_lines:
        for log_line in outcome.log_lines:
            print(f"  {log_line}")
    else:
        print("  (the notification system logged nothing)")


def _labelled(label: str, value: str) -> str:
    """Return one line of the report. The labels line up."""
    return f"{label + ':':<10} {value}"
