# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fallback transport: plain text as mail to the local root (ADR 0008).

The message is handed to the mail command of the host. Proxmox VE forwards
mail to the local root into its notification system as `system-mail` with
severity `unknown`, so this route works without any setup but cannot carry a
severity. That is why the subject starts with it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Final

from pve_smart_alert.config import TransportName
from pve_smart_alert.model import Notification
from pve_smart_alert.paths import SENDMAIL_PATH
from pve_smart_alert.process import ProcessResult, ProcessRunner, run_with_timeout
from pve_smart_alert.transports.base import DEFAULT_TIMEOUT_SECONDS, TransportOutcome

RECIPIENT: Final = "root"


@dataclass(frozen=True)
class MailTransport:
    """Hand a notification to the mail command of the host."""

    sendmail_path: Path = SENDMAIL_PATH
    recipient: str = RECIPIENT
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    runner: ProcessRunner = run_with_timeout
    name: TransportName = TransportName.MAIL

    def send(self, notification: Notification) -> TransportOutcome:
        """Send the notification as mail and report what the command answered."""
        started = time.monotonic()

        if not self.sendmail_path.is_file():
            return self._outcome(
                delivered=False,
                started=started,
                error=f"the mail command is missing at {self.sendmail_path}",
            )

        try:
            message = build_message(notification, recipient=self.recipient)
        except ValueError as failure:
            # A subject that a header cannot carry; the renderer does not write
            # one, so this is a defect, reported instead of ending the run.
            return self._outcome(
                delivered=False, started=started, error=f"the mail could not be built: {failure}"
            )
        try:
            # "-i" keeps a line with a single dot from ending the message,
            # "-t" takes the recipients from the headers.
            result = self.runner(
                [self.sendmail_path, "-i", "-t"], input_text=message, timeout=self.timeout
            )
        except OSError as failure:
            return self._outcome(
                delivered=False,
                started=started,
                error=f"the mail command could not be started: {failure.strerror or failure}",
            )

        error = _reason_for_refusal(result, timeout=self.timeout)
        return self._outcome(delivered=error is None, started=started, error=error, result=result)

    def _outcome(
        self,
        *,
        delivered: bool,
        started: float,
        error: str | None = None,
        result: ProcessResult | None = None,
    ) -> TransportOutcome:
        return TransportOutcome(
            delivered=delivered,
            transport=self.name,
            duration_seconds=time.monotonic() - started,
            log_lines=() if result is None else result.lines,
            error=error,
        )


def build_message(notification: Notification, *, recipient: str) -> str:
    """Return the mail message as it is handed to the mail command.

    The message is built with the standard library, so that a subject or a
    body with characters outside ASCII is encoded the way mail requires.
    """
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = notification.subject
    message.set_content(notification.body)

    return message.as_string()


def _reason_for_refusal(result: ProcessResult, *, timeout: float) -> str | None:
    """Return why the mail command refused the message, or `None`."""
    if result.timed_out:
        return f"the mail command did not answer within {timeout:g} seconds"
    if result.returncode != 0:
        detail = result.lines[-1] if result.lines else ""
        suffix = f": {detail}" if detail else ""
        return f"the mail command ended with exit status {result.returncode}{suffix}"
    return None
