# SPDX-License-Identifier: AGPL-3.0-or-later
"""The transport interface.

A transport hands one notification to the outside world: through the Perl
bridge into the notification system of Proxmox VE, or as mail to the local
root (ADR 0008). The three modes of `notify.transport` (FR-506) are the two
transports and `AutoTransport`, which combines them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final, Protocol

from pve_smart_alert.config import TransportName
from pve_smart_alert.model import MAX_PRINTED, Notification, printed

# How long one transport may take. The delivery to SMTP, Gotify or webhook
# targets happens inside the call, and a slow target must not hold the run
# (ADR 0008). The value is the assumption recorded as Q-N4.
DEFAULT_TIMEOUT_SECONDS: Final = 120.0


@dataclass(frozen=True)
class TransportOutcome:
    """What became of one notification.

    `delivered` is the answer the rest of the tool works with: only after a
    handover may the state that belongs to a notification be stored (FR-517).
    `error` says why it was not delivered. `log_lines` is what the program
    wrote to its standard error, which is what the notification system logged
    about the targets (ARCHITECTURE.md section 10).
    """

    delivered: bool
    transport: TransportName
    duration_seconds: float
    log_lines: tuple[str, ...] = ()
    fallback_reason: str | None = None
    error: str | None = None


class Transport(Protocol):
    """One way of handing a notification over."""

    @property
    def name(self) -> TransportName:
        """The name this transport has in the configuration (FR-506)."""
        ...

    def send(self, notification: Notification) -> TransportOutcome:
        """Hand the notification over and report what happened."""
        ...


@dataclass(frozen=True)
class AutoTransport:
    """Try the primary transport, then the fallback, in the same run (FR-505)."""

    primary: Transport
    fallback: Transport
    name: TransportName = TransportName.AUTO

    def send(self, notification: Notification) -> TransportOutcome:
        """Hand the notification to the primary transport, or to the fallback."""
        primary_outcome = self.primary.send(notification)
        if primary_outcome.delivered:
            return primary_outcome

        reason = primary_outcome.error or "the primary transport failed"
        outcome = self.fallback.send(
            _with_fallback_note(
                notification,
                reason=reason,
                primary=self.primary.name,
                fallback=self.fallback.name,
            )
        )
        return replace(
            outcome,
            fallback_reason=reason,
            log_lines=primary_outcome.log_lines + outcome.log_lines,
            duration_seconds=primary_outcome.duration_seconds + outcome.duration_seconds,
            error=(
                None
                if outcome.delivered
                else f"{reason}; the fallback failed as well: {outcome.error}"
            ),
        )


def _with_fallback_note(
    notification: Notification,
    *,
    reason: str,
    primary: TransportName,
    fallback: TransportName,
) -> Notification:
    """Return the notification with a note that the fallback had to be used.

    The recipient of the fallback message has to see that the usual route is
    broken, and why (ADR 0008).
    """
    # The reason is the answer of an external program, so it is cleaned and
    # cut like a string of a drive before it is written into a mail
    # (ARCHITECTURE.md section 14).
    note = (
        f"The primary transport ({primary}) failed, so this message was sent as {fallback}.\n"
        f"Reason: {printed(reason, limit=MAX_PRINTED)}"
    )
    return replace(notification, body=f"{notification.body.rstrip()}\n\n{note}\n")
