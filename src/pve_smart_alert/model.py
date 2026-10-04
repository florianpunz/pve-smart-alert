# SPDX-License-Identifier: AGPL-3.0-or-later
"""The notification model.

One notification is one message that the tool hands to a transport. This
module holds its shape, the severity vocabulary of the tool, and the mapping
onto the severities of the Proxmox VE notification system (ADR 0008).
"""

from __future__ import annotations

import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

# The value of the `type` field of every notification (FR-502). It is also the
# name of the two template files and of the template the bridge asks for, so
# that a matcher, a webhook body and the templates use the same word
# (ADR 0008).
NOTIFICATION_TYPE: Final = "pve-smart-alert"

FIELD_TYPE: Final = "type"
FIELD_HOSTNAME: Final = "hostname"

# Longer field values are cut. Field values go into the configuration of the
# notification system and drive data is untrusted (ARCHITECTURE.md section 14).
MAX_FIELD_VALUE: Final = 128


class Severity(StrEnum):
    """Severity of the tool, seen from the finding.

    `INFO` is not a finding severity: it carries recoveries, first-run
    summaries without findings and test notifications (ADR 0008, FR-513).
    """

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


class PveSeverity(StrEnum):
    """The severities the Proxmox VE notification system accepts."""

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"


#: How the severities of the tool are named towards Proxmox VE (ADR 0008).
PVE_SEVERITY: Final[Mapping[Severity, PveSeverity]] = {
    Severity.INFO: PveSeverity.INFO,
    Severity.NOTICE: PveSeverity.NOTICE,
    Severity.WARNING: PveSeverity.WARNING,
    Severity.CRITICAL: PveSeverity.ERROR,
}


class EventType(StrEnum):
    """Why a notification is sent (ARCHITECTURE.md section 4)."""

    PROBLEM = "problem"
    ESCALATED = "escalated"
    WORSENED = "worsened"
    REMINDER = "reminder"
    RECOVERED = "recovered"
    MISSING = "missing"
    SUMMARY = "summary"
    FIRST_RUN = "first-run"
    TOOL = "tool"
    TEST = "test"


def sanitize_field_value(value: str, *, limit: int = MAX_FIELD_VALUE) -> str:
    """Return a metadata value that is safe for the notification system.

    A field value never contains a comma, because Proxmox VE splits the value
    list of an exact matcher on commas, so a comma inside a value would change
    the meaning of a rule. Control characters are replaced by spaces and runs
    of whitespace are collapsed, so that a value cannot break the line it is
    written to. The result is cut to `limit` characters (ADR 0008,
    ARCHITECTURE.md section 14).
    """
    without_controls = "".join(
        " " if character < " " or character == "\x7f" else character for character in value
    )
    without_commas = without_controls.replace(",", ";")
    return " ".join(without_commas.split())[:limit]


@dataclass(frozen=True)
class Notification:
    """One message that is ready to be handed to a transport.

    `subject` and `body` are the rendered plain text; both transports send the
    same text. `fields` are the metadata values of the single drive or event
    the notification is about (FR-503); `type` and `hostname` are added by
    `fields_for`. `data` is the structured payload the templates of the
    notification system can use in addition to the two texts.
    """

    event: EventType
    severity: Severity
    subject: str
    body: str
    fields: Mapping[str, str] = field(default_factory=dict)
    data: Mapping[str, object] = field(default_factory=dict)

    def fields_for(self, node: str) -> dict[str, str]:
        """Return the complete metadata fields of this notification.

        Every notification carries `type` and `hostname` (FR-502); the other
        fields describe a single drive (FR-503). The two fixed fields are set
        last, so that a caller cannot replace them by accident: matchers and
        webhook bodies rely on them.
        """
        merged = dict(self.fields)
        merged[FIELD_TYPE] = NOTIFICATION_TYPE
        merged[FIELD_HOSTNAME] = node
        return {name: sanitize_field_value(value) for name, value in merged.items()}


def node_name(hostname: str | None = None) -> str:
    """Return the name of this node, which is its short host name.

    Proxmox VE uses the short host name as the node name, so a fully qualified
    host name is cut at the first dot.
    """
    value = socket.gethostname() if hostname is None else hostname
    return value.split(".", 1)[0]
