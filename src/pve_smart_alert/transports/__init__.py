# SPDX-License-Identifier: AGPL-3.0-or-later
"""The transports of the notification system (ADR 0008).

`build_transport` turns the configured mode into the transport that is used.
The paths of the two programs are parameters so that the tests need neither a
bridge nor a mail command (ADR 0014).
"""

from __future__ import annotations

from pathlib import Path

from pve_smart_alert.config import NotifySettings, TransportName
from pve_smart_alert.paths import BRIDGE_PATH, SENDMAIL_PATH
from pve_smart_alert.transports.base import AutoTransport, Transport, TransportOutcome
from pve_smart_alert.transports.mail import MailTransport
from pve_smart_alert.transports.process import (
    DEFAULT_TIMEOUT_SECONDS,
    ProcessResult,
    ProcessRunner,
    run_with_timeout,
)
from pve_smart_alert.transports.pve_notify import PveNotifyTransport

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "AutoTransport",
    "MailTransport",
    "ProcessResult",
    "ProcessRunner",
    "PveNotifyTransport",
    "Transport",
    "TransportOutcome",
    "build_transport",
    "run_with_timeout",
]


def build_transport(
    settings: NotifySettings,
    *,
    bridge_path: Path = BRIDGE_PATH,
    sendmail_path: Path = SENDMAIL_PATH,
    runner: ProcessRunner = run_with_timeout,
) -> Transport:
    """Return the transport the configuration asks for (FR-506)."""
    primary = PveNotifyTransport(bridge_path=bridge_path, runner=runner)
    fallback = MailTransport(sendmail_path=sendmail_path, runner=runner)

    match settings.transport:
        case TransportName.MAIL:
            return fallback
        case TransportName.PVE_NOTIFY:
            return primary
        case _:
            return AutoTransport(primary=primary, fallback=fallback)
