# SPDX-License-Identifier: AGPL-3.0-or-later
"""The primary transport: the Perl bridge into `PVE::Notify` (ADR 0008).

The bridge is the only code of the tool that touches Proxmox VE internals. It
reads one JSON document from its standard input and answers with one JSON
document on its standard output. What it reports about the targets is what the
notification library logged, which is the only feedback about delivery.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pve_smart_alert.config import TransportName
from pve_smart_alert.model import NOTIFICATION_TYPE, PVE_SEVERITY, Notification
from pve_smart_alert.paths import BRIDGE_PATH
from pve_smart_alert.process import ProcessResult, ProcessRunner, run_with_timeout
from pve_smart_alert.transports.base import DEFAULT_TIMEOUT_SECONDS, TransportOutcome

# The notification library writes what it did with each matched target to the
# standard error of the bridge process. These lines are the only feedback
# about delivery, so the fallback depends on them (ADR 0008). Their wording
# was checked on Proxmox VE 9.2 (ARCHITECTURE.md section 10); if a later
# version changes it, only these three patterns change.
TARGET_SUCCESS: Final = re.compile(r"notified via target", re.IGNORECASE)
TARGET_FAILURE: Final = re.compile(r"could not notify via target", re.IGNORECASE)
RENDER_FAILURE: Final = re.compile(r"failed to render notification template", re.IGNORECASE)


@dataclass(frozen=True)
class PveNotifyTransport:
    """Hand a notification to the notification system of Proxmox VE."""

    bridge_path: Path = BRIDGE_PATH
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    runner: ProcessRunner = run_with_timeout
    name: TransportName = TransportName.PVE_NOTIFY

    def send(self, notification: Notification) -> TransportOutcome:
        """Run the bridge with the notification and report what it answered."""
        started = time.monotonic()

        if not self.bridge_path.is_file():
            return self._outcome(
                delivered=False,
                started=started,
                error=f"the notify bridge is missing at {self.bridge_path}",
            )

        try:
            result = self.runner(
                [self.bridge_path], input_text=_request(notification), timeout=self.timeout
            )
        except OSError as failure:
            return self._outcome(
                delivered=False,
                started=started,
                error=f"the notify bridge could not be started: {failure.strerror or failure}",
            )

        error = reason_for_refusal(result, timeout=self.timeout) or _reason_in_log(result.stderr)
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


def _request(notification: Notification) -> str:
    """Return the JSON document the bridge reads from its standard input."""
    data = dict(notification.data)
    # Set last: what the templates print must be the text that was rendered.
    data["subject"] = notification.subject
    data["body"] = notification.body
    return json.dumps(
        {
            "severity": PVE_SEVERITY[notification.severity].value,
            "template": NOTIFICATION_TYPE,
            "fields": notification.fields_for(),
            "data": data,
        },
        ensure_ascii=False,
    )


def reason_for_refusal(result: ProcessResult, *, timeout: float) -> str | None:
    """Return why the bridge refused, or `None`.

    Used for a notification and for the self-check of the bridge alike: both
    times the answer and the exit status decide.
    """
    if result.timed_out:
        return f"the notify bridge did not answer within {timeout:g} seconds"

    answer_error = _answer_error(result.stdout)
    if answer_error is not None:
        return f"the notify bridge reported an error: {answer_error}"
    if result.returncode != 0:
        detail = result.lines[-1] if result.lines else ""
        suffix = f": {detail}" if detail else ""
        return f"the notify bridge ended with exit status {result.returncode}{suffix}"
    return None


def _answer_error(stdout: str) -> str | None:
    """Return the error of a bridge answer that is not `{"ok": true}`.

    An answer that is not JSON gives `None`; the exit status decides then.
    """
    try:
        answer = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(answer, dict) or answer.get("ok") is True:
        return None
    error = answer.get("error")
    return error if isinstance(error, str) else "no reason given"


def _reason_in_log(stderr: str) -> str | None:
    """Return why no target got the message, or `None` when it was handed over.

    Best effort (ADR 0008): only a line the library is known to write counts.
    `None` also when no matcher matched, which the log does not show; the
    routing check in `routing.py` answers that (ADR 0020). Without a
    recognized line the handover counts as successful, so that a change of
    wording cannot turn every notification into a retry.
    """
    if RENDER_FAILURE.search(stderr):
        return "the notification system could not render the template"
    if TARGET_FAILURE.search(stderr) and not TARGET_SUCCESS.search(stderr):
        return "every matched target of the notification system failed"
    return None
