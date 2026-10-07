# SPDX-License-Identifier: AGPL-3.0-or-later
"""The self-diagnosis of `pve-smart-alert doctor` (FR-603).

Every check answers one line with a status. What this version cannot check
yet is named as one skipped line instead of staying silent, so that the
output never looks more complete than it is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from pve_smart_alert.config import (
    Config,
    ConfigError,
    NotifySettings,
    SmartctlSettings,
    TransportName,
    load_config,
)
from pve_smart_alert.discovery.sources import parse_scan
from pve_smart_alert.model import NOTIFICATION_TYPE, PveSeverity, node_name
from pve_smart_alert.paths import (
    BODY_TEMPLATE,
    BRIDGE_PATH,
    CONFIG_PATH,
    PVESH_PATH,
    REFERENCE_PATH,
    ROOT_FORWARD_PATH,
    SENDMAIL_PATH,
    SUBJECT_TEMPLATE,
    TEMPLATE_DIR,
    TEMPLATE_OVERRIDE_DIR,
)
from pve_smart_alert.process import ProcessRunner, run_with_timeout
from pve_smart_alert.routing import (
    FORWARDED_MAIL_SEVERITY,
    FORWARDED_MAIL_TYPE,
    FORWARDER,
    Blocked,
    NotificationConfig,
    Routing,
    RoutingError,
    Verdict,
    evaluate,
    forwarded_mail_metadata,
    mail_is_forwarded,
    read_notification_config,
    tool_metadata,
)
from pve_smart_alert.transports.base import DEFAULT_TIMEOUT_SECONDS
from pve_smart_alert.transports.pve_notify import reason_for_refusal

# The two files the notification system renders (ADR 0008).
TEMPLATES: Final = (SUBJECT_TEMPLATE, BODY_TEMPLATE)

# What FR-603 asks for and what arrives with its own milestone.
PENDING: Final = (
    "the Proxmox VE version, the timer, the state file, unsupported controllers and smartd"
    " are checked once their milestones are built"
)

# The oldest smartctl that writes JSON (ADR 0002, ADR 0004).
MINIMUM_SMARTCTL: Final = (7, 0)

# How severities that no matcher routes get a route (ADR 0020). The README
# has the complete command.
ROUTING_ADVICE: Final = (
    "add {severities} to a matcher with the rule regex:type=^"
    + NOTIFICATION_TYPE
    + "$, under Datacenter > Notifications, see the README"
)

# How mail to root gets a route (ADR 0022). Forwarded mail always has the
# severity `unknown`, so a severity rule must name it or be left out.
FALLBACK_ADVICE: Final = (
    f"route the type {FORWARDED_MAIL_TYPE} with the severity {FORWARDED_MAIL_SEVERITY},"
    f" for example with a matcher with the rule exact:type={FORWARDED_MAIL_TYPE},"
    " under Datacenter > Notifications"
)


class Status(StrEnum):
    """How one check ended."""

    OK = "ok"
    # Not right, but this host still works: look at it, nothing is broken.
    WARN = "warn"
    FAIL = "fail"
    # Not checked: not part of this version yet, or not possible on this host
    # or with this configuration.
    SKIP = "skip"


@dataclass(frozen=True)
class CheckResult:
    """What one check found."""

    name: str
    status: Status
    detail: str
    advice: str | None = None


def run_doctor(
    *,
    config_path: Path = CONFIG_PATH,
    bridge_path: Path = BRIDGE_PATH,
    sendmail_path: Path = SENDMAIL_PATH,
    template_dir: Path = TEMPLATE_DIR,
    override_dir: Path = TEMPLATE_OVERRIDE_DIR,
    pvesh_path: Path = PVESH_PATH,
    forward_path: Path = ROOT_FORWARD_PATH,
    node: str | None = None,
    runner: ProcessRunner = run_with_timeout,
) -> list[CheckResult]:
    """Run every check and return its results in the order they are reported."""
    config_result, config = check_config(config_path)
    settings = None if config is None else config.notify
    smartctl = SmartctlSettings() if config is None else config.smartctl
    node = node_name() if node is None else node
    # Read once for both routes: every call of pvesh takes seconds.
    routes = read_routes(pvesh_path, runner=runner)

    return [
        config_result,
        check_smartctl(smartctl, runner=runner),
        check_bridge(bridge_path, runner=runner),
        check_templates(template_dir, override_dir=override_dir),
        check_mail(sendmail_path, settings=settings),
        check_routing(routes, settings=settings, node=node, forward_path=forward_path),
        check_fallback(routes, settings=settings, node=node, forward_path=forward_path),
        CheckResult("pending", Status.SKIP, PENDING),
    ]


def check_config(path: Path) -> tuple[CheckResult, Config | None]:
    """Check the configuration file and return it, or `None` when it cannot be used."""
    try:
        config = load_config(path)
    except ConfigError as error:
        return (
            CheckResult(
                "config",
                Status.FAIL,
                f"{path}: {error}",
                advice=f"the keys this version reads are listed in {REFERENCE_PATH}",
            ),
            None,
        )

    if config.source is None:
        result = CheckResult("config", Status.OK, f"no file at {path}, the defaults apply")
        return result, config

    return (
        CheckResult(
            "config",
            Status.OK,
            f"{config.source}: transport = {config.notify.transport.value}",
        ),
        config,
    )


def check_smartctl(
    settings: SmartctlSettings, *, runner: ProcessRunner = run_with_timeout
) -> CheckResult:
    """Check that smartctl is there and writes JSON, and report its version.

    The version comes from the JSON of a device scan that opens no device
    (`--scan`), because `--version` writes no JSON (Research 03).
    """
    path = settings.path
    if not path.is_file():
        return CheckResult(
            "smartctl",
            Status.FAIL,
            f"missing at {path}",
            advice="it comes with the package smartmontools",
        )
    if not os.access(path, os.X_OK):
        return CheckResult("smartctl", Status.FAIL, f"{path} is not executable")

    try:
        result = runner([path, "--scan", "--json=c"], timeout=settings.timeout_seconds)
    except OSError as failure:
        return CheckResult(
            "smartctl",
            Status.FAIL,
            f"{path} could not be started: {failure.strerror or failure}",
        )
    if result.timed_out:
        return CheckResult(
            "smartctl",
            Status.FAIL,
            f"{path} did not answer within {settings.timeout_seconds:g} seconds",
        )

    version = parse_scan(result.stdout).smartctl_version
    if not version or version < MINIMUM_SMARTCTL:
        shown = ".".join(str(part) for part in version) if version else "a version"
        return CheckResult(
            "smartctl",
            Status.FAIL,
            f"{path} answered without JSON of smartctl 7.0 or later, found {shown}",
            advice="the tool needs smartmontools 7.0 or later (ADR 0002)",
        )
    return CheckResult(
        "smartctl", Status.OK, f"{path}: smartctl {'.'.join(str(part) for part in version)}"
    )


def check_bridge(path: Path, *, runner: ProcessRunner = run_with_timeout) -> CheckResult:
    """Check that the bridge is installed and can load the notification system."""
    if not path.is_file():
        return CheckResult(
            "bridge",
            Status.FAIL,
            f"missing at {path}",
            advice="it comes with the pve-smart-alert package",
        )
    if not os.access(path, os.X_OK):
        return CheckResult(
            "bridge",
            Status.FAIL,
            f"{path} is not executable",
            advice="it is the program that talks to the notification system",
        )

    try:
        result = runner([path, "--check"], timeout=DEFAULT_TIMEOUT_SECONDS)
    except OSError as failure:
        return CheckResult(
            "bridge",
            Status.FAIL,
            f"{path} could not be started: {failure.strerror or failure}",
        )

    error = reason_for_refusal(result, timeout=DEFAULT_TIMEOUT_SECONDS)
    if error is not None:
        return CheckResult(
            "bridge",
            Status.FAIL,
            error,
            advice="run it by hand to see what the notification system answers",
        )

    return CheckResult("bridge", Status.OK, "the notification system can be loaded")


def check_templates(template_dir: Path, *, override_dir: Path) -> CheckResult:
    """Check that the notification system finds both template files."""
    directories: set[str] = set()
    missing: list[str] = []
    for name in TEMPLATES:
        path = _template_path(name, template_dir, override_dir)
        if path is None:
            missing.append(name.name)
        else:
            directories.add(str(path.parent))

    if missing:
        return CheckResult(
            "templates",
            Status.FAIL,
            "missing: " + ", ".join(missing),
            advice=(
                f"the package installs them in {template_dir},"
                f" and they can be overridden in {override_dir}"
            ),
        )

    return CheckResult("templates", Status.OK, ", ".join(sorted(directories)))


def check_mail(path: Path, *, settings: NotifySettings | None) -> CheckResult:
    """Check that the mail command of the host is there.

    Only the configuration decides how bad a missing one is: with `mail` or
    `auto` it is the route the message takes, with `pve-notify` it is the
    route that would report a broken run.
    """
    transport = TransportName.AUTO if settings is None else settings.transport
    if path.is_file():
        return CheckResult("mail", Status.OK, str(path))

    detail = f"missing at {path}"
    if transport is TransportName.PVE_NOTIFY:
        return CheckResult(
            "mail",
            Status.WARN,
            detail,
            advice=f"transport = {transport.value} does not need it, but nothing else could report",
        )

    return CheckResult(
        "mail",
        Status.FAIL,
        detail,
        advice=(
            f"transport = {transport.value} needs it, and it takes a mail command such as postfix"
        ),
    )


def read_routes(
    pvesh_path: Path, *, runner: ProcessRunner = run_with_timeout
) -> NotificationConfig | RoutingError:
    """Return the matchers and targets, or why they cannot be read."""
    try:
        return read_notification_config(pvesh_path=pvesh_path, runner=runner)
    except RoutingError as error:
        return error


def check_routing(
    routes: NotificationConfig | RoutingError,
    *,
    settings: NotifySettings | None,
    node: str,
    forward_path: Path = ROOT_FORWARD_PATH,
) -> CheckResult:
    """Check that the matchers route every severity of the tool (ADR 0020).

    A notification that no matcher matches is dropped without an error, so a
    severity without a route is a warning. What this check cannot decide is
    reported as such and never as routed; the notification system remains the
    authority on what is delivered. With `transport = mail` every
    notification goes as mail to root, so that route is checked instead
    (ADR 0022).
    """
    transport = TransportName.AUTO if settings is None else settings.transport
    if transport is TransportName.MAIL:
        return _mail_route(
            "routing",
            routes,
            node=node,
            forward_path=forward_path,
            prefix=f"transport = {transport.value}: ",
        )
    if isinstance(routes, RoutingError):
        return CheckResult("routing", Status.SKIP, f"the matchers cannot be read: {routes}")

    routings = [evaluate(routes, tool_metadata(severity, node=node)) for severity in PveSeverity]
    named = list(zip(PveSeverity, routings, strict=True))
    not_routed = [
        (severity.value, routing)
        for severity, routing in named
        if routing.verdict is Verdict.NOT_ROUTED
    ]
    undecided = [
        severity.value for severity, routing in named if routing.verdict is Verdict.UNKNOWN
    ]

    if not_routed:
        detail = "not routed: " + ", ".join(severity for severity, _ in not_routed)
        if undecided:
            detail += "; cannot be decided for: " + ", ".join(undecided)
        return CheckResult("routing", Status.WARN, detail, advice=_routing_advice(not_routed))

    if undecided:
        reasons = dict.fromkeys(reason for routing in routings for reason in routing.reasons)
        return CheckResult(
            "routing",
            Status.SKIP,
            "cannot be decided for: " + ", ".join(undecided),
            advice="; ".join(reasons),
        )

    matchers = dict.fromkeys(name for routing in routings for name in routing.matchers)
    return CheckResult("routing", Status.OK, "every severity is routed, by " + ", ".join(matchers))


def check_fallback(
    routes: NotificationConfig | RoutingError,
    *,
    settings: NotifySettings | None,
    node: str,
    forward_path: Path = ROOT_FORWARD_PATH,
) -> CheckResult:
    """Check that the fallback, mail to root, reaches a target (ADR 0022).

    Only `transport = auto` has a fallback. When the notify bridge breaks, the
    tool sends mail to root, and that mail is dropped as well if no matcher
    routes it: the tool would fall silent exactly when its fallback is needed.
    """
    transport = TransportName.AUTO if settings is None else settings.transport
    if transport is TransportName.PVE_NOTIFY:
        return CheckResult(
            "fallback", Status.SKIP, f"transport = {transport.value} has no fallback"
        )
    if transport is TransportName.MAIL:
        return CheckResult(
            "fallback",
            Status.SKIP,
            f"transport = {transport.value} has no fallback, mail to root is its route",
        )
    return _mail_route("fallback", routes, node=node, forward_path=forward_path)


def _mail_route(
    name: str,
    routes: NotificationConfig | RoutingError,
    *,
    node: str,
    forward_path: Path,
    prefix: str = "",
) -> CheckResult:
    """Return one line about the route of mail to root (ADR 0022)."""
    forwarded = mail_is_forwarded(forward_path)
    if forwarded is False:
        return CheckResult(
            name,
            Status.WARN,
            f"{prefix}mail to root does not reach the notification system:"
            f" {forward_path} has no line for {FORWARDER}",
            advice=f"reinstalling the package {FORWARDER} writes the line into it",
        )
    if forwarded is None:
        return CheckResult(
            name,
            Status.SKIP,
            f"{prefix}cannot tell whether mail to root reaches the notification system:"
            f" {forward_path} cannot be read",
        )
    if isinstance(routes, RoutingError):
        return CheckResult(name, Status.SKIP, f"{prefix}the matchers cannot be read: {routes}")

    routing = evaluate(routes, forwarded_mail_metadata(node=node))
    if routing.verdict is Verdict.ROUTED:
        return CheckResult(
            name,
            Status.OK,
            f"{prefix}mail to root is routed as {FORWARDED_MAIL_TYPE}, by "
            + ", ".join(routing.matchers),
        )
    if routing.verdict is Verdict.NOT_ROUTED:
        hints = [blocked.describe() for blocked in routing.blocked]
        return CheckResult(
            name,
            Status.WARN,
            f"{prefix}mail to root is not routed: no matcher routes the type"
            f" {FORWARDED_MAIL_TYPE} to an enabled target",
            advice="; ".join(hints) if hints else FALLBACK_ADVICE,
        )
    return CheckResult(
        name,
        Status.SKIP,
        f"{prefix}cannot be decided for mail to root",
        advice="; ".join(routing.reasons),
    )


def _routing_advice(not_routed: list[tuple[str, Routing]]) -> str:
    """Return how the severities that reach no target get a route.

    A matcher whose rules match but that is disabled, or whose targets are
    all disabled, is named with the severities it would route: enabling it
    is the fix, not a new matcher.
    """
    blocked: dict[Blocked, list[str]] = {}
    uncovered: list[str] = []
    for severity, routing in not_routed:
        for hint in routing.blocked:
            blocked.setdefault(hint, []).append(severity)
        if not routing.blocked:
            uncovered.append(severity)

    parts = [hint.describe(", ".join(severities)) for hint, severities in blocked.items()]
    if uncovered:
        parts.append(ROUTING_ADVICE.format(severities=", ".join(uncovered)))
    return "; ".join(parts)


def _template_path(name: Path, template_dir: Path, override_dir: Path) -> Path | None:
    """Return the file the notification system would render, or `None`.

    The override directory comes first, exactly like the lookup of the
    notification system itself (ADR 0008).
    """
    for directory in (override_dir, template_dir):
        candidate = directory / name.name
        if candidate.is_file():
            return candidate
    return None
