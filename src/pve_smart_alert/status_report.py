# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report of `pve-smart-alert status` (FR-602).

Everything comes from the stored state; nothing is read from a drive. The
last run with its time and result, the conditions of the tool, every drive
with its active conditions, the conditions that wait for their
confirmation, the drives that are missing or unreadable, and the skipped
devices. With `--json` the state is printed as it is stored, which is the
machine-readable form (ARCHITECTURE.md section 9).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pve_smart_alert.model import MAX_PRINTED, printable, without_controls
from pve_smart_alert.planner import RANK
from pve_smart_alert.state import ConditionRecord, DriveRecord, State, format_time, state_to_json

_SEVERITY: Final = 10
_CHECK: Final = 26


def render(state: State, *, path: Path) -> list[str]:
    """Return the lines of the report."""
    lines = [f"State:      {path}"]
    run = state.last_run
    if run is None:
        lines.append("Last run:   none yet")
    else:
        lines.append(
            f"Last run:   {format_time(run.started)}, {run.result}; {run.drives_evaluated}"
            f" drives evaluated, {run.drives_skipped} skipped, {run.drives_failed} failed;"
            f" {run.notifications_sent} notifications sent, {run.notifications_failed}"
            " not delivered"
        )
    if state.initialized is None:
        lines.append("            the next run is a first run and sends one summary")

    lines += ["", "pve-smart-alert (the tool itself)"]
    lines += _conditions(state.tool.conditions) or ["  no active conditions"]

    for record in sorted(state.drives.values(), key=lambda item: item.last_access.name):
        lines += ["", _drive_line(record)]
        status = _presence(record)
        if status is not None:
            lines.append(f"  {status}")
        details = _conditions(record.conditions)
        for check, pending in sorted(record.pending.items()):
            details.append(
                f"  {'pending':<{_SEVERITY}}{check:<{_CHECK}} {pending.severity.value},"
                f" seen in {pending.seen_runs} run{'' if pending.seen_runs == 1 else 's'},"
                " waits for its confirmation"
            )
        lines += details or ["  no active conditions"]

    if state.skipped:
        lines += ["", "Skipped devices:"]
        for key, skipped in sorted(state.skipped.items()):
            name, _, device_type = key.partition("|")
            name = printable(name, limit=MAX_PRINTED)
            device_type = printable(device_type, limit=MAX_PRINTED)
            cleaned = printable(skipped.detail, limit=MAX_PRINTED) if skipped.detail else ""
            detail = f" ({cleaned})" if cleaned else ""
            lines.append(
                f"  {name} [{device_type}]: {skipped.reason}{detail}, since"
                f" {format_time(skipped.since)}"
            )
    # The state keeps the strings of the drives as they came: no control
    # character of theirs reaches the terminal (ARCHITECTURE.md section 14).
    return [without_controls(line) for line in lines]


def render_json(state: State, *, path: Path) -> str:
    """Return the state as JSON, with the path it was read from."""
    return json.dumps({"state_file": str(path), **state_to_json(state)}, indent=2) + "\n"


def _drive_line(record: DriveRecord) -> str:
    access = record.last_access
    name = printable(access.name, limit=MAX_PRINTED)
    device_type = printable(access.type, limit=MAX_PRINTED)
    identity = record.identity
    if identity is None:
        return f"{name} [{device_type}], never answered with an identity"
    model = printable(identity.model, limit=MAX_PRINTED)
    serial = printable(identity.serial or "no serial number", limit=MAX_PRINTED)
    return f"{name} [{device_type}] {model} ({serial})"


def _presence(record: DriveRecord) -> str | None:
    """Say when a drive is missing or unreadable, or when it was last seen."""
    seen = format_time(record.last_seen)
    if record.missing_notified:
        return f"missing, notified; last seen {seen}"
    if record.missing_runs:
        runs = record.missing_runs
        return f"not found in {runs} run{'' if runs == 1 else 's'}; last seen {seen}"
    if record.unreadable_runs:
        runs = record.unreadable_runs
        return f"no usable data in {runs} run{'' if runs == 1 else 's'}"
    return None


def _conditions(conditions: dict[str, ConditionRecord]) -> list[str]:
    ordered = sorted(conditions.items(), key=lambda item: (-RANK[item[1].severity], item[0]))
    lines = []
    for check, condition in ordered:
        notified = (
            f"notified {format_time(condition.last_notified)}"
            if condition.last_notified is not None
            else "not notified yet"
        )
        value = f"{condition.current_value}, " if condition.current_value is not None else ""
        lines.append(
            f"  {condition.severity.value.upper():<{_SEVERITY}}{check:<{_CHECK}} {value}since"
            f" {format_time(condition.first_detected)}, {notified}"
        )
    return lines
