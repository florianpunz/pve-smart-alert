# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report of `pve-smart-alert check --dry-run` (FR-601).

One block per monitored drive that has findings, in the order of discovery:
the drive with its name, model and serial number, then one line per finding
with the check, its severity and what the check found. The summary counts the
devices of the run and the findings by severity. The command-line interface
prints the notifications a run would send after it; nothing is sent and no
state is changed.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from pve_smart_alert.discovery import Discovery, Found, Outcome
from pve_smart_alert.model import MAX_PRINTED, Finding, Severity, printed, without_controls

# The width the check identifiers and the severities line up in.
_CHECK_WIDTH: Final = 26
_SEVERITY_WIDTH: Final = 8


def render(
    discovery: Discovery,
    evaluations: Sequence[tuple[Found, list[Finding]]],
    *,
    smartctl_path: Path,
) -> list[str]:
    """Return the lines of the report."""
    lines = [_smartctl_line(discovery, smartctl_path)]
    if discovery.scan_error is not None:
        lines.append(f"Device scan failed: {discovery.scan_error}")
    for found, findings in evaluations:
        if found.outcome is not Outcome.MONITORED or not findings:
            continue
        lines.append("")
        lines.append(_drive_line(found))
        lines.extend(_finding_line(finding) for finding in findings)
    lines.append("")
    lines.append(_summary(discovery, evaluations))
    # No control character of a drive reaches the terminal (ARCHITECTURE.md
    # section 14).
    return [without_controls(line) for line in lines]


def _smartctl_line(discovery: Discovery, path: Path) -> str:
    if not discovery.smartctl_version:
        return f"smartctl at {path}, version not known"
    version = ".".join(str(part) for part in discovery.smartctl_version)
    return f"smartctl {version} at {path}"


def _drive_line(found: Found) -> str:
    candidate = found.candidate
    # The name and the type of a device of the scan need not be valid and
    # can be arbitrarily long (ARCHITECTURE.md section 14).
    name = printed(candidate.name, limit=MAX_PRINTED)
    kind = printed(candidate.type, limit=MAX_PRINTED)
    snapshot = found.snapshot
    if snapshot is None:
        return f"{name} [{kind}]"
    identity = snapshot.identity
    model = printed(identity.model, limit=MAX_PRINTED)
    serial = printed(identity.serial or "no serial number reported", limit=MAX_PRINTED)
    return f"{name} [{kind}] {model}, serial {serial}"


def _finding_line(finding: Finding) -> str:
    # The text of a finding can carry a string of the drive, such as the
    # informational exception of a SCSI drive: it is cut like any other
    # (ARCHITECTURE.md section 14).
    text = printed(finding.text, limit=MAX_PRINTED)
    return f"  {finding.check:<{_CHECK_WIDTH}} {finding.severity.value:<{_SEVERITY_WIDTH}} {text}"


def _summary(discovery: Discovery, evaluations: Sequence[tuple[Found, list[Finding]]]) -> str:
    counts = dict.fromkeys(Outcome, 0)
    for found in discovery.devices:
        counts[found.outcome] += 1
    findings = [finding for _, items in evaluations for finding in items]
    severities = dict.fromkeys((Severity.CRITICAL, Severity.WARNING, Severity.NOTICE), 0)
    for finding in findings:
        severities[finding.severity] += 1
    counted = ", ".join(f"{count} {severity.value}" for severity, count in severities.items())
    total = (
        f"{len(findings)} findings: {counted}"
        if findings
        else "no findings, every drive the checks apply to is within its thresholds"
    )
    return (
        f"{counts[Outcome.MONITORED]} monitored, {counts[Outcome.STANDBY]} in standby,"
        f" {counts[Outcome.UNREADABLE]} unreadable, {counts[Outcome.SKIPPED]} skipped;"
        f" {total}"
    )
