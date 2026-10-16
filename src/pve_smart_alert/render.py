# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rendering the subject and the body of a notification.

The tool renders both texts itself and the templates of the notification
system only pass them through, so that the same text reaches the recipient on
every route and no rendering depends on the Handlebars helpers of a particular
Proxmox VE version (ADR 0008). The layout of a message about a drive is the
one of ARCHITECTURE.md section 10; the structured data goes along for
administrators who override the templates.

Strings that come from a drive, such as the model and the serial number, are
untrusted: they are stripped of control characters and cut before they are
written into a message (ARCHITECTURE.md section 14).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Final

from pve_smart_alert import __version__
from pve_smart_alert.checks import CATALOG, Thresholds
from pve_smart_alert.config import Config, effective_checks
from pve_smart_alert.model import (
    FIELD_DEVICE,
    FIELD_DEVICE_ID,
    FIELD_EVENT,
    FIELD_MODEL,
    FIELD_SERIAL,
    DriveIdentity,
    EventType,
    Notification,
    Severity,
    pass_through_id,
)
from pve_smart_alert.paths import CONFIG_PATH, COROSYNC_CONF_PATH
from pve_smart_alert.planner import RANK, DriveInfo, DriveMessage, Item, MessageKind, Planned
from pve_smart_alert.state import format_time
from pve_smart_alert.tool_conditions import PSEUDO_DEVICE

# Every subject starts here. The severity follows, so that it survives the
# mail route, which carries none (ADR 0008, FR-508).
SUBJECT_PREFIX: Final = "[pve-smart-alert]"

# Strings of a drive are cut to this length in a message.
_MAX_TEXT: Final = 200

# The width of the labels of the header block, and of the severity column.
_LABEL: Final = 12
_SEVERITY: Final = 10


@dataclass(frozen=True)
class Texts:
    """How a check is named in a message.

    `title` names the value in a finding line, `headline` is the short form
    of the subject with `{value}` for the current value, and `advice` says
    what to do.
    """

    title: str
    headline: str
    advice: str
    unit: str = ""


_REPLACE: Final = "Plan a replacement of the drive and make sure its data is backed up."
_REPLACE_NOW: Final = "Replace the drive soon and make sure its data is backed up now."
_COUNTER: Final = "A counter that keeps increasing indicates a failing drive. " + _REPLACE

#: The texts of every check of the catalog and every condition of the tool.
TEXTS: Final[Mapping[str, Texts]] = {
    "health.failed": Texts(
        "Health verdict",
        "health check failed",
        "The drive predicts its own failure. " + _REPLACE_NOW,
    ),
    "selftest.failed": Texts(
        "Last self-test",
        "last self-test failed",
        "The most recent self-test in the drive's log ended with an error. Look at the"
        " self-test log with smartctl -l selftest and plan a replacement.",
    ),
    "temperature": Texts(
        "Temperature",
        "temperature {value} °C",
        "Check the cooling: fans, air flow and the temperature of the room.",
        " °C",
    ),
    "wear": Texts(
        "Wear",
        "{value} % of the rated endurance used",
        "The SSD approaches the end of its rated endurance. " + _REPLACE,
        " %",
    ),
    "smart.disabled": Texts(
        "SMART",
        "SMART is switched off",
        "The tool never changes a drive. Switch SMART on with the command named above"
        " if you want the drive to be monitored.",
    ),
    "drive.unreadable": Texts(
        "Readable",
        "no usable SMART data",
        "Check the cabling, the controller and the kernel log (journalctl -k) for this drive.",
    ),
    "drive.missing": Texts(
        "Present",
        "drive missing",
        "If the drive was removed or replaced on purpose, nothing needs to be done. Otherwise"
        " check whether it failed, and look at the kernel log (journalctl -k).",
    ),
    "ata.attribute_failing": Texts(
        "Attributes",
        "attribute at or below its threshold",
        "The drive reports an attribute at or below the threshold of its vendor. " + _REPLACE,
    ),
    "ata.reallocated_sectors": Texts(
        "Reallocated sectors", "{value} reallocated sectors", _COUNTER
    ),
    "ata.reported_uncorrectable": Texts(
        "Reported uncorrectable errors", "{value} reported uncorrectable errors", _COUNTER
    ),
    "ata.command_timeouts": Texts(
        "Command timeouts",
        "{value} command timeouts",
        "Command timeouts often come from cabling or power. Check both, then watch the value.",
    ),
    "ata.pending_sectors": Texts("Pending sectors", "{value} pending sectors", _COUNTER),
    "ata.offline_uncorrectable": Texts(
        "Offline uncorrectable sectors", "{value} offline uncorrectable sectors", _COUNTER
    ),
    "ata.spin_retries": Texts(
        "Spin retries",
        "{value} spin retries",
        "The disk needed several attempts to spin up. Check its power supply. " + _REPLACE,
    ),
    "ata.end_to_end_errors": Texts(
        "End-to-end errors",
        "{value} end-to-end errors",
        "Data was corrupted inside the drive. " + _REPLACE,
    ),
    "ata.crc_errors": Texts(
        "Interface CRC errors",
        "{value} interface CRC errors",
        "CRC errors come from the connection, not the disk: check or replace the cable and"
        " the port.",
    ),
    "ata.error_log": Texts(
        "ATA error log entries",
        "{value} entries in the ATA error log",
        "Look at the error log with smartctl -l xerror and watch the other findings of the drive.",
    ),
    "nvme.spare": Texts(
        "Available spare",
        "available spare {value} %",
        "The drive runs out of spare blocks. " + _REPLACE,
        " %",
    ),
    "nvme.reliability_degraded": Texts(
        "Reliability",
        "reliability degraded",
        "The drive reports its reliability as degraded. " + _REPLACE_NOW,
    ),
    "nvme.read_only": Texts(
        "Read-only", "drive is read-only", "The drive has switched to read-only. " + _REPLACE_NOW
    ),
    "nvme.backup_failed": Texts(
        "Volatile memory backup",
        "volatile memory backup failed",
        "The drive reports that its volatile memory backup failed. " + _REPLACE_NOW,
    ),
    "nvme.pmr_unreliable": Texts(
        "Persistent memory region",
        "persistent memory region unreliable",
        "The drive reports its persistent memory region as unreliable. " + _REPLACE,
    ),
    "nvme.media_errors": Texts("Media errors", "{value} media errors", _COUNTER),
    "nvme.thermal_excursion": Texts(
        "Minutes above the critical temperature",
        "{value} minutes above the critical temperature",
        "Check the cooling of the drive: a heat sink, the air flow, the fans.",
    ),
    "nvme.error_log": Texts(
        "NVMe error log entries",
        "{value} entries in the NVMe error log",
        "Look at the error log with smartctl -l error and watch the other findings of the drive.",
    ),
    "scsi.grown_defects": Texts("Grown defects", "{value} grown defects", _COUNTER),
    "scsi.uncorrected_errors": Texts("Uncorrected errors", "{value} uncorrected errors", _COUNTER),
    "scsi.pending_defects": Texts("Pending defects", "{value} pending defects", _COUNTER),
    "tool.smartctl_missing": Texts(
        "smartctl",
        "smartctl missing",
        "No drive is monitored. Install the package smartmontools, or correct smartctl.path.",
    ),
    "tool.smartctl_too_old": Texts(
        "smartctl",
        "smartctl too old",
        "No drive is monitored. The tool needs smartmontools 7.0 or later.",
    ),
    "tool.scan_failed": Texts(
        "Device scan",
        "device scan failed",
        "Run pve-smart-alert scan to see what the device scan answers.",
    ),
    "tool.config_invalid": Texts(
        "Configuration",
        "configuration invalid",
        "Run pve-smart-alert config check and correct the file.",
    ),
    "tool.state_reset": Texts(
        "State",
        "state reset",
        "Nothing needs to be done. The tool started afresh and reported what it found.",
    ),
    "tool.transport_degraded": Texts(
        "Notification transport",
        "notification transport degraded",
        "Run pve-smart-alert doctor to see why the notify bridge fails.",
    ),
    "tool.unsupported_controller": Texts(
        "Controller",
        "unsupported controller",
        "The drives behind this controller are not monitored until smartmontools can read"
        " them. Check them with the tool of the controller's vendor, and run"
        " pve-smart-alert doctor to see the controller.",
    ),
}

# The checks whose value is a count of runs, not a value of the drive: their
# text says it all.
_NO_VALUE_LINE: Final = frozenset({"drive.missing", "drive.unreadable"})

# The checks whose text adds to the value: the source of the wear and the
# threshold of the drive itself. A temperature without a threshold was raised
# by the Critical Warning bit of an NVMe drive, which its text names.
_TEXT_ADDS: Final = frozenset({"wear", "nvme.spare"})

# How an event is named in the status of a finding line.
_EVENT_WORDS: Final[Mapping[EventType, str]] = {
    EventType.PROBLEM: "new",
    EventType.ESCALATED: "escalated",
    EventType.WORSENED: "worse",
    EventType.REMINDER: "reminder",
    EventType.RECOVERED: "recovered",
    EventType.MISSING: "missing",
}


@dataclass(frozen=True)
class RenderContext:
    """What a message says besides the plan: the host, the version, the policy."""

    node: str
    config: Config = field(default_factory=Config)
    cluster: str | None = None
    version: str = __version__
    config_path: Path = CONFIG_PATH


def render(planned: Planned, context: RenderContext) -> Notification:
    """Return the notification of one planned message (ADR 0008, FR-507, FR-508)."""
    if planned.kind is MessageKind.DRIVE:
        return _drive(planned, context)
    if planned.kind is MessageKind.SUMMARY:
        return _summary(planned, context)
    if planned.kind is MessageKind.FIRST_RUN:
        return _first_run(planned, context)
    return _tool(planned, context)


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


def cluster_name(path: Path = COROSYNC_CONF_PATH) -> str | None:
    """Return the name of the cluster this node belongs to, or `None`.

    Proxmox VE keeps the corosync configuration of a cluster in
    `/etc/pve/corosync.conf`, and corosync names the cluster with the key
    `cluster_name` of its `totem` section (corosync.conf(5)). A node that is
    not in a cluster has no such file. The file is only read (ADR 0012).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        key, _, value = line.strip().partition(":")
        if key.strip() == "cluster_name" and value.strip():
            return _clean(value.strip())
    return None


# The four kinds of message


def _drive(planned: Planned, context: RenderContext) -> Notification:
    (message,) = planned.drives
    drive = message.drive
    lead = max(message.items, key=_weight)
    subject = f"{_subject_start(planned, context)}: {_drive_name(drive)}: {_headline(lead)}"
    lines = [_opening(message, context.node), ""]
    lines += _host(context)
    lines += _drive_block(drive)
    lines += ["", "Findings:"]
    lines += _findings(message, context)
    if message.active:
        lines += ["", "Also active, nothing new:"]
        lines += [_short(item) for item in message.active]
    lines += _advice(message.items)
    closing = _closing(message, context)
    if closing:
        lines += ["", *closing]
    lines += ["", _signature(context)]
    fields = {
        FIELD_EVENT: message.event.value,
        FIELD_DEVICE: drive.name,
        FIELD_SERIAL: _clean(drive.serial or ""),
        FIELD_MODEL: _clean(drive.model or ""),
    }
    # `device-id` comes from the type of the current read, or of the last one
    # for a missing drive. A drive read without a pass-through type has no
    # such field at all, not an empty one (ADR 0029).
    device_id = pass_through_id(drive.type)
    if device_id is not None:
        fields[FIELD_DEVICE_ID] = device_id
    return Notification(
        event=message.event,
        severity=planned.severity,
        node=context.node,
        subject=subject,
        body=_text(lines),
        fields={name: value for name, value in fields.items() if value},
        data=_data(planned),
    )


def _summary(planned: Planned, context: RenderContext) -> Notification:
    count = len(planned.drives)
    subject = f"{_subject_start(planned, context)}: {count} drives need attention"
    limit = context.config.notify.max_drive_notifications
    lines = [
        f"{count} drives in {context.node} have notifications in the same run. They are sent",
        f"as one summary instead of one message per drive (limit: {limit}).",
        "",
    ]
    lines += _host(context)
    for message in planned.drives:
        lines += ["", _drive_line(message.drive)]
        lines += _findings(message, context)
    lines += _advice([item for message in planned.drives for item in message.items])
    lines += ["", f"To adjust the checks or the policy, see {context.config_path}."]
    lines += ["", _signature(context)]
    return Notification(
        event=EventType.SUMMARY,
        severity=planned.severity,
        node=context.node,
        subject=subject,
        body=_text(lines),
        fields={FIELD_EVENT: EventType.SUMMARY.value},
        data=_data(planned),
    )


def _first_run(planned: Planned, context: RenderContext) -> Notification:
    drives = len(planned.drives)
    findings = sum(len(message.items) for message in planned.drives)
    monitored = f"monitoring {drives} drive{'' if drives == 1 else 's'}"
    found = f"{findings} finding{'' if findings == 1 else 's'}" if findings else "no findings"
    subject = f"{_subject_start(planned, context)}: {monitored}, {found}"
    lines = [
        *_wrapped(
            f"PVE SMART Alert now monitors the drives of {context.node}. This summary lists"
            " what it found. From now on a problem is reported once, again when it gets"
            " worse, and as a reminder after a while.",
            "",
        ),
        "",
    ]
    if planned.state_reset is not None:
        lines += [
            "The state file could not be used and was set aside, so the tool started afresh:",
            f"  {_clean(planned.state_reset)}",
            "",
        ]
    lines += _host(context)
    lines += ["", "Monitored drives:"]
    if not planned.drives:
        lines.append("  none")
    for message in planned.drives:
        status = "" if message.items else "  no findings"
        lines.append(f"  {_drive_line(message.drive)}{status}")
        lines += [f"  {_short(item)}" for item in message.items]
    if planned.unreadable:
        lines += ["", "Devices without usable data:"]
        for seen in planned.unreadable:
            reason = f": {_clean(seen.reason)}" if seen.reason else ""
            lines.append(f"  {seen.access.name} [{seen.access.type}]{reason}")
    if planned.skipped:
        lines += ["", "Skipped devices:"]
        for skipped in planned.skipped:
            detail = f" ({_clean(skipped.detail)})" if skipped.detail else ""
            lines.append(
                f"  {skipped.access.name} [{skipped.access.type}]: {skipped.reason}{detail}"
            )
    tool = [item for item in planned.tool if item.check != "tool.state_reset"]
    if tool:
        lines += ["", "Problems of the tool itself:"]
        lines += [_short(item) for item in tool]
    existing = [item for message in planned.drives for item in message.items] + tool
    if existing:
        lines += _advice(existing)
    lines += [
        "",
        *_wrapped(
            "This message also shows that notifications reach you. It is sent once; it can"
            f" be switched off with first_run_summary = false in [notify] of"
            f" {context.config_path}.",
            "",
        ),
        "",
        _signature(context),
    ]
    return Notification(
        event=EventType.FIRST_RUN,
        severity=planned.severity,
        node=context.node,
        subject=subject,
        body=_text(lines),
        fields={FIELD_EVENT: EventType.FIRST_RUN.value},
        data=_data(planned),
    )


def _tool(planned: Planned, context: RenderContext) -> Notification:
    lead = max(planned.tool, key=_weight)
    subject = f"{_subject_start(planned, context)}: {PSEUDO_DEVICE}: {_headline(lead)}"
    recovered = all(item.event is EventType.RECOVERED for item in planned.tool)
    opening = (
        f"A problem of PVE SMART Alert itself on {context.node} is solved."
        if recovered
        else f"PVE SMART Alert on {context.node} has a problem of its own."
    )
    lines = [opening, ""]
    lines += _host(context)
    lines += ["", "Findings:"]
    for item in planned.tool:
        lines += _finding(item, None)
    if planned.tool_active:
        lines += ["", "Also active, nothing new:"]
        lines += [_short(item) for item in planned.tool_active]
    lines += _advice(planned.tool)
    lines += ["", _signature(context)]
    event = max(planned.tool, key=_weight).event
    return Notification(
        event=EventType.TOOL,
        severity=planned.severity,
        node=context.node,
        subject=subject,
        body=_text(lines),
        fields={FIELD_EVENT: event.value, FIELD_DEVICE: PSEUDO_DEVICE},
        data=_data(planned),
    )


# Parts of a message


def _subject_start(planned: Planned, context: RenderContext) -> str:
    return f"{SUBJECT_PREFIX} {planned.severity.value.upper()} {context.node}"


def _drive_name(drive: DriveInfo) -> str:
    """Return a drive as the subject names it: device, model and serial number (FR-508)."""
    model = _clean(drive.model or "unknown model")
    serial = _clean(drive.serial) if drive.serial else "no serial number"
    if drive.model is None:
        return drive.name
    return f"{drive.name} {model} ({serial})"


def _drive_line(drive: DriveInfo) -> str:
    described = _drive_name(drive).removeprefix(drive.name).strip()
    return f"{drive.name} [{drive.type}] {described}".rstrip()


def _opening(message: DriveMessage, node: str) -> str:
    events = {item.event for item in message.items}
    if events == {EventType.RECOVERED}:
        return f"A drive in {node} has recovered."
    if events == {EventType.MISSING}:
        return f"A drive of {node} is missing."
    return f"A drive in {node} needs attention."


def _host(context: RenderContext) -> list[str]:
    cluster = f" (cluster: {context.cluster})" if context.cluster else ""
    return [_labelled("Host", f"{context.node}{cluster}")]


def _drive_block(drive: DriveInfo) -> list[str]:
    """Return the header block of a drive (FR-507)."""
    where = f"{drive.name} [{drive.type}]"
    if not drive.present and drive.last_seen is not None:
        where += f", last read {format_time(drive.last_seen)}"
    lines = [_labelled("Drive", where)]
    if drive.model is not None:
        lines.append(_labelled("Model", _clean(drive.model)))
    if drive.serial is not None:
        lines.append(_labelled("Serial", _clean(drive.serial)))
    if drive.wwn is not None:
        lines.append(_labelled("WWN", _clean(drive.wwn)))
    if drive.firmware is not None:
        lines.append(_labelled("Firmware", _clean(drive.firmware)))
    kind = drive.drive_class.value.upper() if drive.drive_class is not None else None
    capacity = _capacity(drive.capacity_bytes)
    if capacity or kind:
        lines.append(_labelled("Capacity", ", ".join(part for part in (capacity, kind) if part)))
    if drive.location is not None:
        lines.append(_labelled("Location", _clean(drive.location)))
    if drive.used_by is not None:
        lines.append(_labelled("Used by", _clean(drive.used_by)))
    if drive.power_on_hours is not None:
        lines.append(_labelled("Powered on", f"{drive.power_on_hours} hours"))
    return lines


def _findings(message: DriveMessage, context: RenderContext) -> list[str]:
    thresholds = _thresholds_of(message.drive, context.config)
    lines = []
    for item in message.items:
        lines += _finding(item, thresholds.get(item.check))
    return lines


def _finding(item: Item, thresholds: Thresholds | None) -> list[str]:
    """Return the lines of one finding: check, severity, value, previous value, threshold."""
    indent = " " * (2 + _SEVERITY)
    if item.event is EventType.RECOVERED:
        head = f"  {'RECOVERED':<{_SEVERITY}}{item.check}"
        return [
            head,
            f"{indent}{_title(item)}: no longer found in the last runs; it was"
            f" {item.severity.value}{_was(item)}",
        ]
    status = _EVENT_WORDS.get(item.event, item.event.value)
    if item.event is EventType.ESCALATED and item.previous_severity is not None:
        status = f"escalated from {item.previous_severity.value}"
    lines = [f"  {item.severity.value.upper():<{_SEVERITY}}{item.check}  {status}"]
    if item.value is None or item.check in _NO_VALUE_LINE:
        lines += _wrapped(f"{_title(item)}: {_clean(item.text)}", indent)
    else:
        lines.append(f"{indent}{_title(item)}: {_value_text(item)}")
        if item.check in _TEXT_ADDS or (item.check == "temperature" and item.threshold is None):
            lines += _wrapped(_clean(item.text), indent)
    if thresholds is not None:
        lines.append(f"{indent}Thresholds: {_thresholds_text(thresholds, _unit(item))}")
    elif item.threshold is not None:
        lines.append(f"{indent}Threshold: {item.threshold}{_unit(item)}")
    if item.since is not None and item.event not in (EventType.PROBLEM, EventType.MISSING):
        lines.append(f"{indent}Active since {format_time(item.since)}")
    return lines


def _short(item: Item) -> str:
    if item.value is None or item.check in _NO_VALUE_LINE:
        return f"  {item.severity.value.upper():<{_SEVERITY}}{item.check}: {_clean(item.text)}"
    return f"  {item.severity.value.upper():<{_SEVERITY}}{item.check}: {_value_text(item)}"


def _value_text(item: Item) -> str:
    """Return the value of a finding, with the previous one where there is one."""
    unit = _unit(item)
    text = f"{item.value}{unit}"
    if item.previous is not None and item.previous != item.value:
        text += f" (previous: {item.previous}{unit})"
    return text


def _was(item: Item) -> str:
    if item.previous is None:
        return ""
    return f" at {item.previous}{_unit(item)}"


def _advice(items: Sequence[Item]) -> list[str]:
    """Return what to do, for the most severe finding that needs something done."""
    open_items = [item for item in items if item.event is not EventType.RECOVERED]
    if not open_items:
        return ["", "Nothing needs to be done for these findings anymore."]
    lead = max(open_items, key=_weight)
    texts = TEXTS.get(lead.check)
    if texts is None:
        return []
    return ["", "What to do:", *_wrapped(texts.advice, "  ")]


def _closing(message: DriveMessage, context: RenderContext) -> list[str]:
    """Return what happens next: the reminder, or that this was the last message."""
    open_items = [item for item in message.items if item.event is not EventType.RECOVERED]
    if not open_items:
        return []
    lead = max(open_items, key=_weight)
    if lead.event is EventType.MISSING:
        first = "This is the only notification about the missing drive."
    elif lead.event is EventType.PROBLEM:
        first = "This is the first notification for this problem."
    else:
        first = "The problem was notified before."
    interval = context.config.notify.reminder.interval(lead.severity.value)
    if lead.event is EventType.MISSING:
        nxt = "If it returns, its findings are evaluated as usual."
    elif interval is None:
        nxt = f"Without a change, no reminder follows for a {lead.severity.value}."
    else:
        nxt = f"Without a change, the next reminder follows in {interval_text(interval)}."
    return _wrapped(
        f"{first} {nxt} To adjust or silence this check for this drive, see {context.config_path}.",
        "",
    )


def _signature(context: RenderContext) -> str:
    return f"pve-smart-alert {context.version} on {context.node}"


def _data(planned: Planned) -> dict[str, object]:
    """Return the structured data for templates that an administrator overrides (ADR 0008)."""
    drives = [
        {
            "device": message.drive.name,
            "type": message.drive.type,
            "model": _clean(message.drive.model or ""),
            "serial": _clean(message.drive.serial or ""),
            "wwn": message.drive.wwn,
            "present": message.drive.present,
            "event": message.event.value if message.items else None,
            "severity": message.severity.value if message.items else None,
            "findings": [_item_data(item) for item in message.items],
        }
        for message in planned.drives
        if message.items or planned.kind is MessageKind.FIRST_RUN
    ]
    return {
        "event": planned.event.value,
        "severity": planned.severity.value,
        "drives": drives,
        "findings": [
            {**_item_data(item), "device": message.drive.name}
            for message in planned.drives
            for item in message.items
        ]
        + [{**_item_data(item), "device": PSEUDO_DEVICE} for item in planned.tool],
    }


def _item_data(item: Item) -> dict[str, object]:
    return {
        "check": item.check,
        "event": item.event.value,
        "severity": item.severity.value,
        "value": item.value,
        "previous": item.previous,
        "threshold": item.threshold,
        "text": _clean(item.text),
    }


# Small helpers


def _headline(item: Item) -> str:
    texts = TEXTS.get(item.check)
    if texts is None:
        return item.check
    if item.event is EventType.RECOVERED:
        return f"recovered: {texts.title.lower()}"
    if "{value}" in texts.headline:
        if item.value is None:
            return texts.title.lower()
        return texts.headline.format(value=item.value)
    return texts.headline


def _title(item: Item) -> str:
    texts = TEXTS.get(item.check)
    return texts.title if texts is not None else item.check


def _unit(item: Item) -> str:
    texts = TEXTS.get(item.check)
    return texts.unit if texts is not None else ""


def _weight(item: Item) -> tuple[int, int]:
    """Order the items of a message: open ones before recoveries, then by severity."""
    return (0 if item.event is EventType.RECOVERED else 1, RANK[item.severity])


def _thresholds_of(drive: DriveInfo, config: Config) -> dict[str, Thresholds]:
    """Return the effective thresholds of every check for a drive (FR-507)."""
    if drive.model is None or drive.drive_class is None:
        return {}
    identity = DriveIdentity.of(drive.model, serial=drive.serial, wwn=drive.wwn)
    settings = effective_checks(config, identity, drive.drive_class)
    return {
        name: item.thresholds
        for name, item in settings.items()
        if item.thresholds is not None and name != "nvme.spare" and name in CATALOG
    }


def _thresholds_text(thresholds: Thresholds, unit: str) -> str:
    parts = [
        f"{name} {value}{unit}"
        for name, value in (
            ("notice", thresholds.notice),
            ("warning", thresholds.warning),
            ("critical", thresholds.critical),
        )
        if value is not None
    ]
    return ", ".join(parts)


def _capacity(size: int | None) -> str | None:
    """Return a capacity as drive vendors write it, in powers of ten."""
    if size is None or size <= 0:
        return None
    for unit, factor in (("TB", 10**12), ("GB", 10**9), ("MB", 10**6)):
        if size >= factor:
            return f"{size / factor:.2f} {unit}"
    return f"{size} bytes"


def _labelled(label: str, value: str) -> str:
    return f"{label + ':':<{_LABEL}}{value}"


def _clean(value: str | None, *, limit: int = _MAX_TEXT) -> str:
    """Return a string from a drive, safe to write into a message (ARCHITECTURE.md section 14)."""
    if value is None:
        return ""
    without_controls = "".join(
        " " if character < " " or character == "\x7f" else character for character in value
    )
    return " ".join(without_controls.split())[:limit]


def _wrapped(text: str, indent: str, width: int = 78) -> list[str]:
    """Return a paragraph wrapped to a width, each line with the indent."""
    lines: list[str] = []
    current = indent
    for word in text.split():
        candidate = f"{current} {word}" if current.strip() else f"{indent}{word}"
        if len(candidate) > width and current.strip():
            lines.append(current)
            current = f"{indent}{word}"
        else:
            current = candidate
    if current.strip():
        lines.append(current)
    return lines


def _text(lines: Sequence[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def interval_text(value: timedelta | None) -> str:
    """Return an interval for a message, such as "7 days" or "6 hours"."""
    if value is None:
        return "never"
    seconds = int(value.total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size and seconds % size == 0:
            count = seconds // size
            return f"{count} {unit}{'' if count == 1 else 's'}"
    return f"{seconds} seconds"
