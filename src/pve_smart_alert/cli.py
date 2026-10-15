# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command-line interface of PVE SMART Alert.

The commands of later milestones are added here as they arrive. A run of
`check` is put together by `run.py`; this module only builds its environment
from the paths of the host, so that the tests can replace each of them.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from pve_smart_alert import __version__
from pve_smart_alert.anonymize import AnonymizationError
from pve_smart_alert.check_report import render as render_check_report
from pve_smart_alert.config import (
    Config,
    ConfigError,
    NotifySettings,
    TransportName,
    load_config,
    load_effective,
    save_last_good,
)
from pve_smart_alert.config_report import render as render_config_report
from pve_smart_alert.discovery import Candidate, Found, discover
from pve_smart_alert.doctor import CheckResult, Status, run_doctor
from pve_smart_alert.dump import DumpError, dump_fixture
from pve_smart_alert.model import (
    PVE_SEVERITY,
    SEVERITY_FOR_PVE,
    Finding,
    Notification,
    PveSeverity,
    node_name,
)
from pve_smart_alert.paths import (
    BRIDGE_PATH,
    CONFIG_PATH,
    COROSYNC_CONF_PATH,
    LAST_GOOD_CONFIG_PATH,
    LOCK_PATH,
    ROOT_FORWARD_PATH,
    STATE_PATH,
)
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
from pve_smart_alert.run import Environment, LockedError, RunResult, run_check
from pve_smart_alert.scan_report import render
from pve_smart_alert.state import read_state
from pve_smart_alert.status_report import render as render_status
from pve_smart_alert.status_report import render_json as render_status_json
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
# Another run holds the lock. Not an error of the run that holds it (FR-605).
EXIT_LOCKED = 3

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

    commands.add_parser(
        "scan",
        help="find the drives of this host and show what each one is",
        description=(
            "Find the drives of this host, read each of them once, and show every device"
            " found with its source and what became of it."
        ),
    )

    dump = commands.add_parser(
        "dump-fixture",
        help="record the drive data of this host as an anonymized archive",
        description=(
            "Record the device scan, lsblk and the output of smartctl for the drives,"
            " with serial numbers, WWNs and UUIDs replaced by placeholders, as one archive."
        ),
    )
    dump.add_argument(
        "devices", nargs="*", metavar="DEVICE", help="a device to record, such as /dev/sda"
    )
    dump.add_argument("--all", action="store_true", help="record every device found")
    dump.add_argument(
        "--output",
        type=Path,
        default=Path(),
        help="the directory the archive is written to (default: the current one)",
    )

    check = commands.add_parser(
        "check",
        help="evaluate the drives of this host and send the notifications that are due",
        description=(
            "Run one check: evaluate the drives of this host against the checks of the"
            " catalog, compare the result with the state of earlier runs, send the"
            " notifications that are due and save the state (FR-601)."
        ),
    )
    check.add_argument(
        "--dry-run",
        action="store_true",
        help="print the findings and the planned notifications; send nothing, change nothing",
    )

    status = commands.add_parser(
        "status",
        help="show the stored state: the last run and the active conditions",
        description=(
            "Show, from the stored state, the last run and every drive with its active"
            " conditions (FR-602). Nothing is read from a drive."
        ),
    )
    status.add_argument("--json", action="store_true", help="print the state as JSON")

    config = commands.add_parser(
        "config",
        help="work with the configuration file",
        description="Validate the configuration file, or show the effective configuration.",
    )
    config_commands = config.add_subparsers(dest="config_command", metavar="COMMAND")
    config_commands.required = True
    config_commands.add_parser(
        "check",
        help="validate the configuration file",
        description=(
            "Validate the whole configuration file. Errors name the key and the"
            " line, and the command exits non-zero (FR-405)."
        ),
    )
    show = config_commands.add_parser(
        "show",
        help="print the effective configuration",
        description=(
            "Print every key with its effective value and where the value comes"
            " from, the file or the built-in default (FR-407)."
        ),
    )
    show.add_argument(
        "--defaults",
        action="store_true",
        help="print the built-in defaults instead of the effective configuration",
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
    if arguments.command == "scan":
        return _scan()
    if arguments.command == "check":
        return _check_dry_run() if arguments.dry_run else _check()
    if arguments.command == "status":
        return _status(as_json=arguments.json)
    if arguments.command == "config":
        if arguments.config_command == "check":
            return _config_check()
        return _config_show(defaults=arguments.defaults)
    if arguments.command == "dump-fixture":
        if arguments.all == bool(arguments.devices):
            parser.error("dump-fixture needs either --all or the devices to record")
        return _dump_fixture(arguments)

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
        settings = replace(settings, transport=TransportName(arguments.transport))

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
    decided = False
    if outcome.delivered:
        matchers, decided = _matchers(notification, outcome)
        print(_labelled("Matchers", matchers))

    print("Log:")
    if outcome.log_lines:
        for log_line in outcome.log_lines:
            print(f"  {log_line}")
    elif outcome.transport is not TransportName.PVE_NOTIFY:
        # Mail to root never brings an answer of the notification system.
        print("  (the mail command logged nothing)")
    else:
        print("  (the notification system logged nothing)")
        if outcome.delivered and not decided:
            # Only when the line Matchers could not answer it (ADR 0020).
            print("  Nothing logged can also mean that no matcher matched: check the target.")


def _matchers(notification: Notification, outcome: TransportOutcome) -> tuple[str, bool]:
    """Return which matchers route the delivered test notification.

    The second value says whether that was decided: whether the line answers
    where the notification went, or only why it cannot.

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
            ), True
        if forwarded is None:
            return f"cannot be decided: {ROOT_FORWARD_PATH} cannot be read", False
        metadata = forwarded_mail_metadata(node=notification.node)
        what = "mail to root"
        suffix = f", as {FORWARDED_MAIL_TYPE}"

    try:
        config = read_notification_config()
    except RoutingError as error:
        return f"cannot be read: {error}", False

    routing = evaluate(config, metadata)
    if routing.verdict is Verdict.ROUTED:
        return ", ".join(routing.matchers) + suffix, True
    if routing.verdict is Verdict.NOT_ROUTED:
        hints = [blocked.describe() for blocked in routing.blocked]
        return "; ".join([f"none, no matcher routes {what} to an enabled target", *hints]), True
    return "cannot be decided: " + "; ".join(routing.reasons), False


def _labelled(label: str, value: str) -> str:
    """Return one line of the report. The labels line up."""
    return f"{label + ':':<10} {value}"


def _scan() -> int:
    """Find the drives of this host and show what each one is (FR-108)."""
    try:
        config = load_config()
    except ConfigError as error:
        print(f"{PROGRAM}: {error}", file=sys.stderr)
        return EXIT_USAGE

    discovery = discover(config, on_device=_reading)
    for line in render(discovery, smartctl_path=config.smartctl.path):
        print(line)
    return EXIT_PROBLEM if discovery.scan_error is not None else EXIT_OK


def _reading(candidate: Candidate) -> None:
    """Show on standard error which device is read, since a read can take long.

    Only on a terminal: a run of the timer logs one summary line to the
    journal, not one line per drive (FR-606).
    """
    if sys.stderr.isatty():
        print(f"reading {candidate.name} [{candidate.type}] ...", file=sys.stderr)


def clock() -> datetime:
    """The time of a run. The scenario tests replace it (ADR 0016)."""
    return datetime.now(UTC)


def _environment() -> Environment:
    """Return the environment of a run, from the paths of this host."""
    return Environment(
        config_path=CONFIG_PATH,
        last_good=LAST_GOOD_CONFIG_PATH,
        state_path=STATE_PATH,
        lock_path=LOCK_PATH,
        bridge_path=BRIDGE_PATH,
        corosync_path=COROSYNC_CONF_PATH,
        clock=clock,
        node=node_name,
        transport=build_transport,
        discover=discover,
        on_device=_reading,
    )


def _check() -> int:
    """Run one check and send what is due (FR-601, FR-606, FR-607)."""
    try:
        result = run_check(_environment())
    except LockedError as error:
        print(f"{PROGRAM}: {error}; this run is skipped", file=sys.stderr)
        return EXIT_LOCKED
    except OSError as error:
        # The lock or the state directory cannot be used, typically without
        # the rights of root.
        print(f"{PROGRAM}: the run failed: {error}", file=sys.stderr)
        return EXIT_PROBLEM

    _warn_about_config(result)
    for delivery in result.deliveries:
        outcome = delivery.outcome
        if outcome is not None and outcome.delivered:
            via = outcome.transport.value
            if outcome.fallback_reason is not None:
                via += f", because {outcome.fallback_reason}"
            print(f"sent ({via}): {delivery.notification.subject}")
        else:
            reason = outcome.error if outcome is not None else "not sent"
            print(f"not delivered ({reason}): {delivery.notification.subject}")
    print(f"{PROGRAM}: {result.summary}")
    return EXIT_OK if result.ok else EXIT_PROBLEM


def _check_dry_run() -> int:
    """Print the findings and the planned notifications; send and change nothing (FR-601)."""
    result = run_check(_environment(), dry_run=True)
    _warn_about_config(result)
    if result.state_error is not None:
        print(
            f"{PROGRAM}: {result.state_error}; a run would set the file aside and start afresh",
            file=sys.stderr,
        )

    findings: list[Finding] = []
    if result.discovery is not None:
        evaluations: list[tuple[Found, list[Finding]]] = [
            (found, result.findings.get(found.candidate.name, []))
            for found in result.discovery.monitored
        ]
        for line in render_check_report(
            result.discovery, evaluations, smartctl_path=result.config.smartctl.path
        ):
            print(line)
        findings = [finding for _, items in evaluations for finding in items]

    print("")
    _print_plan(result)
    return EXIT_PROBLEM if findings else EXIT_OK


def _print_plan(result: RunResult) -> None:
    """Print what a run would send now, and say that nothing was sent."""
    if not result.deliveries:
        print("Planned notifications: none")
    else:
        print("Planned notifications:")
        for delivery in result.deliveries:
            notification = delivery.notification
            print(f"  {notification.event.value:<10} {notification.subject}")
    print("Nothing was sent and no state was changed (dry run).")


def _warn_about_config(result: RunResult) -> None:
    """Name the error of an invalid configuration on standard error (FR-406)."""
    if result.config_error is None:
        return
    print(f"{PROGRAM}: {result.config_error}", file=sys.stderr)
    fallback = (
        "the last good configuration"
        if result.config.source == LAST_GOOD_CONFIG_PATH
        else "the built-in defaults"
    )
    print(f"{PROGRAM}: runs continue with {fallback}", file=sys.stderr)


def _status(*, as_json: bool) -> int:
    """Show the stored state (FR-602)."""
    state, error = read_state(STATE_PATH, now=clock())
    if error is not None:
        print(f"{PROGRAM}: {error}", file=sys.stderr)
        return EXIT_PROBLEM
    if state is None:
        if as_json:
            print(json.dumps({"state_file": str(STATE_PATH), "schema": None}))
        else:
            print(f"State:      {STATE_PATH} does not exist yet")
            print("            the next run is a first run and sends one summary")
        return EXIT_OK
    if as_json:
        print(render_status_json(state, path=STATE_PATH), end="")
    else:
        for line in render_status(state, path=STATE_PATH):
            print(line)
    return EXIT_OK


def _config_check() -> int:
    """Validate the configuration file (FR-405, FR-407)."""
    try:
        config = load_config(CONFIG_PATH)
    except ConfigError as error:
        print(f"{CONFIG_PATH}: {error}")
        return EXIT_PROBLEM

    _save_last_good(config)
    where = config.source if config.source is not None else f"no file at {CONFIG_PATH}"
    print(f"{where}: valid")
    return EXIT_OK


def _config_show(*, defaults: bool) -> int:
    """Print the effective configuration and the origin of each value (FR-407)."""
    raw = None if defaults else _raw_document(CONFIG_PATH)
    if defaults:
        config, error = Config(), None
    else:
        config, error = load_effective(last_good=LAST_GOOD_CONFIG_PATH)
    if error is not None:
        # What a run uses is shown even then, and the error with it.
        print(f"{PROGRAM}: {error}", file=sys.stderr)

    for line in render_config_report(config, raw, error=error):
        print(line)
    return EXIT_OK


def _raw_document(path: Path) -> dict[str, object] | None:
    """Return the configuration file as parsed, or `None` when it cannot be read."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None


def _save_last_good(config: Config) -> None:
    """Save the effective configuration as the last good one (ADR 0011).

    A save that does not work, for example without the rights to write the
    state directory, does not stop the command: the answer of the command
    matters more, and the next run as root saves again.
    """
    try:
        save_last_good(config, LAST_GOOD_CONFIG_PATH)
    except OSError as error:
        print(f"{PROGRAM}: the last good configuration was not saved: {error}", file=sys.stderr)


def _dump_fixture(arguments: argparse.Namespace) -> int:
    """Record the drive data of this host, anonymized, as one archive (FR-604)."""
    try:
        config = load_config()
    except ConfigError as error:
        print(f"{PROGRAM}: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        dump = dump_fixture(
            config,
            devices=None if arguments.all else arguments.devices,
            output=arguments.output,
            node=node_name(),
            now=datetime.now(UTC),
        )
    except (DumpError, AnonymizationError, OSError) as error:
        print(f"{PROGRAM}: nothing was written: {error}", file=sys.stderr)
        return EXIT_PROBLEM

    print(_labelled("Written", str(dump.archive)))
    print(_labelled("Devices", ", ".join(dump.devices) or "none"))
    print("Serial numbers, WWNs and UUIDs are replaced by placeholders. Model names, firmware")
    print("versions and the node name are kept; look at the archive before you share it.")
    return EXIT_OK


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
