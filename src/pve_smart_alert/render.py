# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rendering the subject and the body of a notification.

The tool renders both texts itself and the templates of the notification
system only pass them through, so that the same text reaches the recipient on
every route and no rendering depends on the Handlebars helpers of a particular
Proxmox VE version (ADR 0008).
"""

from __future__ import annotations

from typing import Final

from pve_smart_alert.model import FIELD_EVENT, EventType, Notification, Severity

# Every subject starts here. The severity follows, so that it survives the
# mail route, which carries none (ADR 0008, FR-508).
SUBJECT_PREFIX: Final = "[pve-smart-alert]"


def render_test_notification(severity: Severity, *, node: str) -> Notification:
    """Return the notification that `test-notification` sends (FR-520).

    The severity is the one the administrator chose; the default of the
    command is `info`, because a test is not a finding (ADR 0008).
    """
    return Notification(
        event=EventType.TEST,
        severity=severity,
        node=node,
        subject=f"{SUBJECT_PREFIX} {severity.value.upper()} {node}: test notification",
        body=(
            f"This is a test notification from PVE SMART Alert on {node}.\n"
            "\n"
            "It was sent by `pve-smart-alert test-notification`. No drive is involved\n"
            "and nothing needs to be done: if this message reaches you, the notification\n"
            "path works.\n"
        ),
        fields={FIELD_EVENT: EventType.TEST.value},
        data={"event": EventType.TEST.value},
    )
