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
from pve_smart_alert.doctor import CheckResult, Status, run_doctor
from pve_smart_alert.model import (
    PVE_SEVERITY,
    SEVERITY_FOR_PVE,
    Notification,
    PveSeverity,
    node_name,
)
from pve_smart_alert.paths import ROOT_FORWARD_PATH
from pve_smart_alert.render import render_test_notification
from pve_smart_alert.routing import (
    FORWARDED_MAIL_TYPE,
    FORWARDER,
    RoutingError,
    Verdict,
    evaluate,
    forwarded_mail_metadata,
    mail_is_forwarded,
    metadata_of,
    read_notification_config,
)
from pve_smart_alert.transports import TransportOutcome, build_transport

PROGRAM = "pve-smart-alert"
DESCRIPTION = "SMART drive alerts for Proxmox VE"

# The command ran and answered well.
EXIT_OK = 0
# The command ran, but its answer is not a good one: a notification that was
# not delivered or a check that failed. That is the answer, not a crash
# (FR-520, FR-603).
EXIT_PROBLEM = 1
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

    commands.add_parser(
        "doctor",
        help="check what this host offers for the tool",
        description="Check the parts of the host the tool works with and report one line each.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the program and return its exit status."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "test-notification":
        return _test_notification(arguments)
    if arguments.command == "doctor":
        return _doctor()

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

    return EXIT_OK if outcome.delivered else EXIT_PROBLEM


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
    if outcome.delivered:
        print(_labelled("Matchers", _matchers(notification, outcome)))

    print("Log:")
    if outcome.log_lines:
        for log_line in outcome.log_lines:
            print(f"  {log_line}")
    else:
        print("  (the notification system logged nothing)")
        print("  Nothing logged can also mean that no matcher matched: check the target.")


def _matchers(notification: Notification, outcome: TransportOutcome) -> str:
    """Return which matchers route the delivered test notification.

    The notification system accepts a notification that no matcher matches
    and drops it without an error, so the answer of the transport alone
    cannot tell whether it went anywhere (ADR 0020). A test that went as mail
    to root is followed as the notification the mail forwarder makes of it
    (ADR 0022).
    """
    if outcome.transport is TransportName.PVE_NOTIFY:
        metadata = metadata_of(notification)
        what = "this notification"
        suffix = ""
    else:
        forwarded = mail_is_forwarded()
        if forwarded is False:
            return (
                "none, mail to root does not reach the notification system:"
                f" {ROOT_FORWARD_PATH} has no line for {FORWARDER}"
            )
        if forwarded is None:
            return f"cannot be decided: {ROOT_FORWARD_PATH} cannot be read"
        metadata = forwarded_mail_metadata(node=notification.node)
        what = "mail to root"
        suffix = f", as {FORWARDED_MAIL_TYPE}"

    try:
        config = read_notification_config()
    except RoutingError as error:
        return f"cannot be read: {error}"

    routing = evaluate(config, metadata)
    if routing.verdict is Verdict.ROUTED:
        return ", ".join(routing.matchers) + suffix
    if routing.verdict is Verdict.NOT_ROUTED:
        hints = [blocked.describe() for blocked in routing.blocked]
        return "; ".join([f"none, no matcher routes {what} to an enabled target", *hints])
    return "cannot be decided: " + "; ".join(routing.reasons)


def _labelled(label: str, value: str) -> str:
    """Return one line of the report. The labels line up."""
    return f"{label + ':':<10} {value}"


def _doctor() -> int:
    """Report what this host offers for the tool (FR-603)."""
    results = run_doctor()
    for result in results:
        print(_check_line(result))
        if result.advice is not None:
            # Starts where the detail of the line above starts.
            print(f"{'':<12} {'':<5} {result.advice}")

    return EXIT_PROBLEM if any(_failed(result) for result in results) else EXIT_OK


def _check_line(result: CheckResult) -> str:
    """Return one line of the self-diagnosis. Names and statuses line up."""
    return f"{result.name + ':':<12} {result.status.value:<5} {result.detail}"


def _failed(result: CheckResult) -> bool:
    return result.status is Status.FAIL
