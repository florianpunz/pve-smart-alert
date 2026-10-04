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

from pve_smart_alert.config import ConfigError, NotifySettings, TransportName, load_config
from pve_smart_alert.paths import (
    BODY_TEMPLATE,
    BRIDGE_PATH,
    CONFIG_PATH,
    SENDMAIL_PATH,
    SUBJECT_TEMPLATE,
    TEMPLATE_DIR,
    TEMPLATE_OVERRIDE_DIR,
)
from pve_smart_alert.transports.process import (
    DEFAULT_TIMEOUT_SECONDS,
    ProcessRunner,
    run_with_timeout,
)
from pve_smart_alert.transports.pve_notify import reason_for_refusal

# The two files the notification system renders (ADR 0008).
TEMPLATES: Final = (SUBJECT_TEMPLATE, BODY_TEMPLATE)

# What FR-603 asks for and what arrives with its own milestone.
PENDING: Final = (
    "smartctl, the Proxmox VE version, the timer, the state file and smartd"
    " are checked once their milestones are built"
)


class Status(StrEnum):
    """How one check ended."""

    OK = "ok"
    # Not right, but this host still works: look at it, nothing is broken.
    WARN = "warn"
    FAIL = "fail"
    # Not part of this version yet.
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
    runner: ProcessRunner = run_with_timeout,
) -> list[CheckResult]:
    """Run every check and return its results in the order they are reported."""
    config_result, settings = check_config(config_path)

    return [
        config_result,
        check_bridge(bridge_path, runner=runner),
        check_templates(template_dir, override_dir=override_dir),
        check_mail(sendmail_path, settings=settings),
        CheckResult("pending", Status.SKIP, PENDING),
    ]


def check_config(path: Path) -> tuple[CheckResult, NotifySettings | None]:
    """Check the configuration file and return it as the settings of the run."""
    try:
        config = load_config(path)
    except ConfigError as error:
        return (
            CheckResult(
                "config",
                Status.FAIL,
                f"{path}: {error}",
                advice="this version reads only the key notify.transport",
            ),
            None,
        )

    if config.source is None:
        result = CheckResult("config", Status.OK, f"no file at {path}, the defaults apply")
        return result, config.notify

    return (
        CheckResult(
            "config",
            Status.OK,
            f"{config.source}: transport = {config.notify.transport.value}",
        ),
        config.notify,
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
