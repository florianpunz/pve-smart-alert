# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discovery: which drives a host has, and what each of them is (ADR 0005).

A pipeline of four steps:

1. Sources: the device scan of smartctl, then the manual entries of the
   configuration (FR-104).
2. Enrichment from lsblk, the links below /dev/disk and sysfs, best effort.
3. Filtering. A device on a remote transport or one that is not a disk is
   skipped before it is read. A drive that reports no SMART capability, or
   that an exclude rule selects (ADR 0024), is skipped after it was read,
   because only its output tells what it is (FR-107).
4. De-duplication: a drive reachable through several paths is kept once, by
   its identity, preferably through a block device of the host and through
   the scan; the other paths are recorded as aliases (FR-106).

Every device found is reported with what became of it, so that
`pve-smart-alert scan` can show each one (FR-108). Nothing here stops for a
single device (FR-205).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum

from pve_smart_alert.collect import Collected, Status, collect_drive
from pve_smart_alert.config import Config
from pve_smart_alert.discovery.enrichment import (
    HOST,
    NOT_DISKS,
    BlockDevices,
    Details,
    HostPaths,
    details_of,
    is_remote,
    read_block_devices,
)
from pve_smart_alert.discovery.sources import (
    Candidate,
    Source,
    manual_candidates,
    run_scan,
)
from pve_smart_alert.model import Collection, DeviceAccess, DriveIdentity, Snapshot
from pve_smart_alert.parsers import ParseError, parse
from pve_smart_alert.process import ProcessRunner, run_with_timeout

__all__ = [
    "Candidate",
    "Discovery",
    "Found",
    "HostPaths",
    "Outcome",
    "SkipReason",
    "Source",
    "discover",
]


class Outcome(StrEnum):
    """What became of one device in this run."""

    MONITORED = "monitored"
    # Asleep and not woken (FR-203).
    STANDBY = "standby"
    # No usable data in this run (FR-205).
    UNREADABLE = "unreadable"
    SKIPPED = "skipped"


class SkipReason(StrEnum):
    """Why a device is skipped, as `pve-smart-alert scan` names it (ARCHITECTURE.md section 5)."""

    EXCLUDED = "excluded"
    REMOTE = "remote"
    NOT_A_DISK = "not-a-disk"
    # Recognized from milestone M6 on, with recordings of RAID controllers.
    LOGICAL_VOLUME = "logical-volume"
    NO_SMART = "no-smart"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class Found:
    """One device of the discovery and what became of it.

    `detail` says why a device is unreadable, which power mode it sleeps in,
    which rule excluded it, or which path a duplicate is the same drive as.
    """

    candidate: Candidate
    outcome: Outcome
    snapshot: Snapshot | None = None
    collected: Collected | None = None
    reason: SkipReason | None = None
    detail: str | None = None
    details: Details = field(default_factory=Details)


@dataclass(frozen=True)
class Discovery:
    """Every device of one run, in the order they were found."""

    devices: tuple[Found, ...]
    smartctl_version: tuple[int, ...] = ()
    scan_error: str | None = None
    enrichment_error: str | None = None

    @property
    def monitored(self) -> tuple[Found, ...]:
        return tuple(found for found in self.devices if found.outcome is Outcome.MONITORED)


def discover(
    config: Config,
    *,
    runner: ProcessRunner = run_with_timeout,
    paths: HostPaths = HOST,
    on_device: Callable[[Candidate], None] | None = None,
) -> Discovery:
    """Find the drives of this host and read each of them once.

    `on_device` is called before each device is read, so that a command can
    show progress.
    """
    settings = config.smartctl
    scan = run_scan(settings, runner=runner)
    block_devices = read_block_devices(paths, runner=runner)
    candidates = list(scan.candidates) + list(manual_candidates(config.discovery.devices))

    found: list[Found] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        if (candidate.name, candidate.type) in seen:
            found.append(
                Found(
                    candidate,
                    Outcome.SKIPPED,
                    reason=SkipReason.DUPLICATE,
                    detail="listed twice",
                )
            )
            continue
        seen.add((candidate.name, candidate.type))
        if on_device is not None:
            on_device(candidate)
        found.append(_examine(candidate, config, block_devices, paths=paths, runner=runner))

    version = scan.smartctl_version or next(
        (item.collected.smartctl_version for item in found if item.collected is not None), ()
    )
    return Discovery(
        devices=_deduplicate(found),
        smartctl_version=version,
        scan_error=scan.error,
        enrichment_error=block_devices.error,
    )


def _examine(
    candidate: Candidate,
    config: Config,
    block_devices: BlockDevices,
    *,
    paths: HostPaths,
    runner: ProcessRunner,
) -> Found:
    """Return what one device is, reading it unless it is skipped before."""
    if not candidate.valid:
        return Found(
            candidate,
            Outcome.UNREADABLE,
            detail="the name or the type has a form that is not passed to smartctl",
        )

    details = details_of(candidate.name, block_devices, paths)
    if is_remote(details, candidate.name):
        return Found(
            candidate,
            Outcome.SKIPPED,
            reason=SkipReason.REMOTE,
            detail=f"transport {details.location.transport}",
            details=details,
        )
    if details.lsblk_type in NOT_DISKS:
        return Found(
            candidate,
            Outcome.SKIPPED,
            reason=SkipReason.NOT_A_DISK,
            detail=f"lsblk type {details.lsblk_type}",
            details=details,
        )

    collected = collect_drive(
        candidate.name,
        candidate.type,
        settings=config.smartctl,
        protocol=candidate.protocol,
        runner=runner,
    )
    if collected.status is Status.STANDBY:
        return Found(
            candidate,
            Outcome.STANDBY,
            collected=collected,
            detail=collected.reason,
            details=details,
        )
    if collected.status is Status.UNREADABLE or collected.document is None:
        return Found(
            candidate,
            Outcome.UNREADABLE,
            collected=collected,
            detail=collected.reason,
            details=details,
        )

    try:
        snapshot = parse(
            collected.document,
            access=DeviceAccess(candidate.name, candidate.type, candidate.protocol or ""),
            collection=Collection(
                smartctl_version=collected.smartctl_version,
                exit_status=collected.exit_status or 0,
                messages=collected.messages,
                duration_seconds=collected.duration_seconds,
            ),
        )
    except ParseError as error:
        return Found(
            candidate, Outcome.UNREADABLE, collected=collected, detail=str(error), details=details
        )
    snapshot = replace(snapshot, location=details.location, membership=details.membership)

    if snapshot.smart_available is False:
        return Found(
            candidate,
            Outcome.SKIPPED,
            snapshot=snapshot,
            collected=collected,
            reason=SkipReason.NO_SMART,
            detail="the drive reports no SMART capability",
            details=details,
        )
    for rule in config.discovery.exclude:
        if rule.matches(snapshot.identity):
            return Found(
                candidate,
                Outcome.SKIPPED,
                snapshot=snapshot,
                collected=collected,
                reason=SkipReason.EXCLUDED,
                detail=rule.describe(),
                details=details,
            )
    return Found(
        candidate, Outcome.MONITORED, snapshot=snapshot, collected=collected, details=details
    )


def _deduplicate(found: list[Found]) -> tuple[Found, ...]:
    """Keep one path per drive and record the others as its aliases (ADR 0005).

    Only a stable identity is compared: two drives without serial number and
    WWN may well be two drives.
    """
    kept: dict[DriveIdentity, int] = {}
    result = list(found)
    for index, item in enumerate(found):
        snapshot = item.snapshot
        if item.outcome is not Outcome.MONITORED or snapshot is None:
            continue
        if not snapshot.identity.stable:
            continue
        previous = kept.get(snapshot.identity)
        if previous is None:
            kept[snapshot.identity] = index
            continue
        keep, drop = (index, previous) if _preferred(item, result[previous]) else (previous, index)
        kept[snapshot.identity] = keep
        result[keep] = _with_alias(result[keep], result[drop].candidate.name)
        result[drop] = replace(
            result[drop],
            outcome=Outcome.SKIPPED,
            reason=SkipReason.DUPLICATE,
            detail=f"the same drive as {result[keep].candidate.name}",
        )
    return tuple(result)


def _preferred(first: Found, second: Found) -> bool:
    """Whether `first` is the better path to a drive than `second`.

    A block device of the host before a pass-through path, the scan before a
    manual entry; otherwise the one found first stays.
    """

    def rank(item: Found) -> tuple[bool, bool]:
        return item.details.block_device, item.candidate.source is Source.SCAN

    return rank(first) > rank(second)


def _with_alias(found: Found, alias: str) -> Found:
    snapshot = found.snapshot
    if snapshot is None:
        return found
    access = replace(snapshot.access, aliases=(*snapshot.access.aliases, alias))
    return replace(found, snapshot=replace(snapshot, access=access))
