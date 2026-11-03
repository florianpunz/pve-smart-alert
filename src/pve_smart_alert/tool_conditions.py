# SPDX-License-Identifier: AGPL-3.0-or-later
"""The conditions of the tool itself (docs/check-catalog.md, ADR 0009).

They are reported like the conditions of a drive, on a pseudo-device named
after the tool: once, reminded per severity, and cleared with a recovery
(FR-518). This module lists them and finds out, at the start of a run,
which of them hold. `tool.state_reset` is a one-time event that the
planner mentions in the summary after the reset. `tool.unsupported_controller`
is read from the SCSI hosts that discovery found in sysfs (ADR 0030).

Every one of them can be switched off in the configuration like a check of a
drive, with `enabled = false` in the table `[checks."<id>"]` (FR-408, ADR
0031). The notice
about a controller whose drives cannot be read names how many drives the run
monitors on the host and how that notice is switched off for a controller in
HBA mode, whose drives all appear in the scan.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pve_smart_alert.config import ConfigError, NotifySettings, SmartctlSettings, TransportName
from pve_smart_alert.discovery.controllers import ScsiHost, describe_all
from pve_smart_alert.model import CheckKind, Finding, Severity
from pve_smart_alert.process import ProcessRunner, run_with_timeout
from pve_smart_alert.transports.base import DEFAULT_TIMEOUT_SECONDS
from pve_smart_alert.transports.pve_notify import reason_for_refusal

__all__ = [
    "MINIMUM_SMARTCTL",
    "PSEUDO_DEVICE",
    "TOOL_CONDITIONS",
    "UNSUPPORTED_CONTROLLER",
    "ToolCondition",
    "config_invalid",
    "scan_failed",
    "smartctl_missing",
    "smartctl_too_old",
    "transport_degraded",
    "unsupported_controller",
]

#: The name of the pseudo-device the conditions of the tool are reported on.
PSEUDO_DEVICE: Final = "pve-smart-alert"

#: The oldest smartctl that writes JSON (ADR 0002, ADR 0004).
MINIMUM_SMARTCTL: Final = (7, 0)

# The first line of `smartctl --version`, for example
# "smartctl 7.5 2025-04-30 r5714 [x86_64-linux-6.14.8-2-pve] (local build)".
_VERSION_LINE: Final = re.compile(r"^smartctl (\d+)\.(\d+)", re.MULTILINE)


@dataclass(frozen=True)
class ToolCondition:
    """One condition of the tool, with its fixed severity (docs/check-catalog.md)."""

    id: str
    severity: Severity
    kind: CheckKind = CheckKind.CONDITION


#: The condition of the controllers whose drives cannot be read (ADR 0030).
UNSUPPORTED_CONTROLLER: Final = "tool.unsupported_controller"

# What the notice about such a controller says about switching it off (ADR
# 0031): a controller in HBA mode, whose drives the scan lists, needs no
# notice, and the configuration of the tool switches it off like a check. The
# setting is a dotted key, so that the line is valid TOML and can be pasted
# into the configuration as it is (ADR 0040).
_SWITCH_OFF: Final = (
    "; if the controller runs in HBA mode and its drives all appear in scan,"
    ' switch this notice off with checks."tool.unsupported_controller".enabled = false'
)

#: Every condition of the tool, by its stable identifier.
TOOL_CONDITIONS: Final[Mapping[str, ToolCondition]] = {
    condition.id: condition
    for condition in (
        ToolCondition("tool.smartctl_missing", Severity.CRITICAL),
        ToolCondition("tool.smartctl_too_old", Severity.CRITICAL),
        ToolCondition("tool.scan_failed", Severity.WARNING),
        ToolCondition("tool.config_invalid", Severity.WARNING),
        ToolCondition("tool.state_reset", Severity.NOTICE, CheckKind.EVENT),
        ToolCondition("tool.transport_degraded", Severity.WARNING),
        ToolCondition("tool.unsupported_controller", Severity.NOTICE),
    )
}


def finding(check: str, text: str) -> Finding:
    """Return the finding of one condition of the tool."""
    condition = TOOL_CONDITIONS[check]
    return Finding(check=check, kind=condition.kind, severity=condition.severity, text=text)


def smartctl_missing(settings: SmartctlSettings) -> Finding | None:
    """Return `tool.smartctl_missing` when smartctl cannot be executed (ARCHITECTURE.md 11)."""
    path = settings.path
    if not path.is_file():
        return finding("tool.smartctl_missing", f"smartctl was not found at {path}")
    if not os.access(path, os.X_OK):
        return finding("tool.smartctl_missing", f"smartctl at {path} is not executable")
    return None


def smartctl_too_old(
    settings: SmartctlSettings,
    version: tuple[int, ...],
    *,
    runner: ProcessRunner = run_with_timeout,
) -> Finding | None:
    """Return `tool.smartctl_too_old` for a smartctl older than 7.0.

    `version` is the one the device scan answered with. A smartctl older
    than 7.0 writes no JSON, so its scan fails and the version is asked for
    in text, which every version writes on its first line.
    """
    if not version:
        version = _text_version(settings, runner)
    if version and version < MINIMUM_SMARTCTL:
        shown = ".".join(str(part) for part in version)
        return finding(
            "tool.smartctl_too_old",
            f"smartctl at {settings.path} is version {shown}; the tool needs 7.0 or later",
        )
    return None


def scan_failed(error: str | None) -> Finding | None:
    """Return `tool.scan_failed` when the device scan brought nothing usable."""
    if error is None:
        return None
    return finding("tool.scan_failed", f"the device scan failed: {error}")


def config_invalid(error: ConfigError, *, fallback: str) -> Finding:
    """Return `tool.config_invalid`: the file is invalid, and what runs use instead (FR-406)."""
    return finding(
        "tool.config_invalid",
        f"the configuration file is invalid: {error}; runs continue with {fallback}",
    )


def transport_degraded(
    settings: NotifySettings,
    bridge_path: Path,
    *,
    runner: ProcessRunner = run_with_timeout,
) -> Finding | None:
    """Return `tool.transport_degraded` when the notify bridge cannot be used.

    The bridge is asked to load the notification system without sending
    anything, as `pve-smart-alert doctor` does. With `transport = mail` there
    is no bridge to fail.
    """
    if settings.transport is TransportName.MAIL:
        return None
    reason = _bridge_problem(bridge_path, runner)
    if reason is None:
        return None
    if settings.transport is TransportName.AUTO:
        consequence = "notifications are sent as mail to root, without their severity"
    else:
        consequence = "notifications cannot be delivered"
    return finding("tool.transport_degraded", f"{reason}; {consequence}")


def unsupported_controller(
    hosts: Sequence[ScsiHost], monitored: int | None = None
) -> Finding | None:
    """Return `tool.unsupported_controller` for SCSI hosts whose drives cannot be read.

    One condition for all of them, which names each host and its driver; it
    clears with a recovery when the last of them is gone (ADR 0030). It also
    names how many drives this run monitors on the host, as far as the run
    could count them, and how the notice is switched off for a controller
    whose drives all appear in the scan (ADR 0031).
    """
    if not hosts:
        return None
    return finding(
        UNSUPPORTED_CONTROLLER,
        describe_all(hosts) + _monitored_text(monitored) + _SWITCH_OFF,
    )


def _monitored_text(monitored: int | None) -> str:
    """Return what the notice says about the drives this run monitors (ADR 0031).

    The count is left out where the run could not count, which is the case
    without smartctl and with a failed device scan: then it did not look for
    all drives, and it reports that situation as a condition of its own.
    """
    if monitored is None:
        return ""
    if monitored == 0:
        return "; no drive is monitored on this host"
    if monitored == 1:
        return "; 1 drive is monitored on this host"
    return f"; {monitored} drives are monitored on this host"


def _bridge_problem(path: Path, runner: ProcessRunner) -> str | None:
    if not path.is_file():
        return f"the notify bridge is missing at {path}"
    try:
        result = runner([path, "--check"], timeout=DEFAULT_TIMEOUT_SECONDS)
    except OSError as failure:
        return f"the notify bridge could not be started: {failure.strerror or failure}"
    return reason_for_refusal(result, timeout=DEFAULT_TIMEOUT_SECONDS)


def _text_version(settings: SmartctlSettings, runner: ProcessRunner) -> tuple[int, ...]:
    try:
        result = runner([settings.path, "--version"], timeout=settings.timeout_seconds)
    except OSError:
        return ()
    match = _VERSION_LINE.search(result.stdout)
    if match is None:
        return ()
    return (int(match.group(1)), int(match.group(2)))
