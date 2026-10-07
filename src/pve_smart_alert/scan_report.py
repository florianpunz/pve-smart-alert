# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report of `pve-smart-alert scan` (FR-108).

One block per device found, in the order of discovery: its name, type and
source, what became of it, and for a drive that was read what the tool knows
about it: identity, class, what uses it, the wear value with its source, and
how long smartctl took. A wear value that differs by 10 percentage points or
more from what the web interface of Proxmox VE shows names both (ADR 0021).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from pve_smart_alert.discovery import Discovery, Found, Outcome, Source
from pve_smart_alert.model import Membership, Snapshot
from pve_smart_alert.parsers.wear import WEAR_METRIC, WEB_INTERFACE_METRIC

# From this difference on, both values are shown (ADR 0021).
WEAR_DIFFERENCE: Final = 10

_SOURCES: Final = {Source.SCAN: "from the scan", Source.MANUAL: "manual entry"}


def render(discovery: Discovery, *, smartctl_path: Path) -> list[str]:
    """Return the lines of the report."""
    lines = [_smartctl_line(discovery, smartctl_path)]
    if discovery.scan_error is not None:
        lines.append(f"Device scan failed: {discovery.scan_error}")
    if discovery.enrichment_error is not None:
        lines.append(
            f"Without lsblk: {discovery.enrichment_error}; transport, links and use are missing"
        )
    for found in discovery.devices:
        lines.append("")
        lines.extend(_device(found))
    lines.append("")
    lines.append(_summary(discovery))
    return lines


def _smartctl_line(discovery: Discovery, path: Path) -> str:
    if not discovery.smartctl_version:
        return f"smartctl at {path}, version not known"
    version = ".".join(str(part) for part in discovery.smartctl_version)
    return f"smartctl {version} at {path}"


def _device(found: Found) -> Iterator[str]:
    candidate = found.candidate
    yield f"{candidate.name} [{candidate.type}], {_SOURCES[candidate.source]}: {_outcome(found)}"
    snapshot = found.snapshot
    if snapshot is not None:
        yield from _drive(snapshot)
    elif found.detail is not None and found.outcome is not Outcome.STANDBY:
        yield _labelled("Reason", found.detail)
    if found.collected is not None:
        yield _labelled("Read in", f"{found.collected.duration_seconds:.2f} s")


def _outcome(found: Found) -> str:
    if found.outcome is Outcome.SKIPPED:
        reason = found.reason.value if found.reason is not None else "skipped"
        return f"skipped, {reason}" + (f" ({found.detail})" if found.detail else "")
    if found.outcome is Outcome.STANDBY:
        return f"in standby ({found.detail}), not woken" if found.detail else "in standby"
    return found.outcome.value


def _drive(snapshot: Snapshot) -> Iterator[str]:
    identity = snapshot.identity
    yield _labelled("Model", identity.model)
    yield _labelled("Serial", identity.serial or "none reported")
    if identity.wwn is not None:
        yield _labelled("WWN", identity.wwn)
    if snapshot.firmware is not None:
        yield _labelled("Firmware", snapshot.firmware)
    if snapshot.capacity_bytes is not None:
        yield _labelled("Capacity", f"{snapshot.capacity_bytes / 1e9:.2f} GB")
    transport = snapshot.location.transport
    yield _labelled(
        "Class", snapshot.drive_class.value + (f", transport {transport}" if transport else "")
    )
    yield _labelled("Used by", _membership(snapshot.membership))
    wear = _wear(snapshot)
    if wear is not None:
        yield _labelled("Wear", wear)
    if snapshot.access.aliases:
        yield _labelled("Aliases", ", ".join(snapshot.access.aliases))


def _membership(membership: Membership) -> str:
    uses = []
    if membership.volume_group is not None:
        uses.append(f"LVM volume group {membership.volume_group}")
    if membership.zfs_pool is not None:
        uses.append(f"ZFS pool {membership.zfs_pool}")
    if membership.md_array is not None:
        uses.append(f"md array {membership.md_array}")
    return ", ".join(uses) if uses else "nothing that lsblk shows"


def _wear(snapshot: Snapshot) -> str | None:
    """Return the wear with its source, and the value of the web interface if it differs."""
    used = snapshot.metrics.get(WEAR_METRIC)
    if used is None:
        return None
    source = snapshot.wear_source.value if snapshot.wear_source is not None else "unknown source"
    text = f"{used} % ({source})"
    shown = snapshot.metrics.get(WEB_INTERFACE_METRIC)
    if shown is not None and abs(shown - used) >= WEAR_DIFFERENCE:
        text += f", the web interface shows {shown} %"
    return text


def _summary(discovery: Discovery) -> str:
    counts = dict.fromkeys(Outcome, 0)
    for found in discovery.devices:
        counts[found.outcome] += 1
    return (
        f"{counts[Outcome.MONITORED]} monitored, {counts[Outcome.STANDBY]} in standby,"
        f" {counts[Outcome.UNREADABLE]} unreadable, {counts[Outcome.SKIPPED]} skipped"
    )


def _labelled(label: str, value: str) -> str:
    """Return one line below a device. The values line up."""
    return f"  {label + ':':<10} {value}"
