# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discovery: which drives a host has, and what each of them is (ADR 0005).

Sources: the device scan, the HPE probe (ADR 0032), then manual entries;
lsblk, /dev/disk and sysfs only enrich. A device is filtered, de-duplicated
by identity and reported with what became of it (FR-106 to FR-109). A device
that cannot be read or parsed becomes an unreadable outcome (FR-205).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from pve_smart_alert.collect import Collected, Status, collect_drive
from pve_smart_alert.config import Config, SmartctlSettings, drive_override
from pve_smart_alert.discovery.controllers import ScsiHost, ScsiHosts, read_scsi_hosts
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
from pve_smart_alert.discovery.probes import HpeController, Probing, probe_hpe
from pve_smart_alert.discovery.sources import (
    Candidate,
    Source,
    manual_candidates,
    run_scan,
)
from pve_smart_alert.discovery.volumes import (
    DISK_TYPES,
    asks_for_megaraid,
    inquiry_text,
    logical_volume,
)
from pve_smart_alert.model import (
    Collection,
    DeviceAccess,
    DriveIdentity,
    Snapshot,
)
from pve_smart_alert.parsers import ParseError, inquiry_of, parse, protocol_of
from pve_smart_alert.process import ProcessRunner, run_with_timeout

__all__ = [
    "Candidate",
    "Discovery",
    "Found",
    "HostPaths",
    "HpeController",
    "Outcome",
    "Probing",
    "ScsiHost",
    "ScsiHosts",
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
    # A logical volume of a RAID controller (ADR 0028).
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
    # The SCSI hosts of sysfs, for the controllers whose drives cannot be
    # read (FR-109, ADR 0030) and for the HPE Smart Array probe (FR-103,
    # ADR 0032).
    scsi_hosts: ScsiHosts = field(default_factory=ScsiHosts)
    # The HPE Smart Array controllers this run looked at, and what the probe
    # read behind them.
    probe: Probing = field(default_factory=Probing)

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
    """Find the drives of this host and read them.

    A drive that two sources find is read twice and kept once. `on_device`
    is called before each device is read, so that a command can show
    progress.
    """
    settings = config.smartctl
    scan = run_scan(settings, runner=runner)
    block_devices = read_block_devices(paths, runner=runner)
    scsi_hosts = read_scsi_hosts(paths)

    found: list[Found] = []
    seen: set[tuple[str, str]] = set()
    for candidate in scan.candidates:
        found.append(
            _read_or_skip(
                candidate,
                config,
                block_devices,
                seen,
                paths=paths,
                runner=runner,
                on_device=on_device,
            )
        )
    # The probe comes after the scan and before the manual entries
    # (ARCHITECTURE.md section 5); a drive the scan found as well is read twice
    # and kept once (FR-106).
    probing = probe_hpe(
        scsi_hosts.hosts,
        probe_cciss=config.discovery.probe_cciss,
        smartctl=settings,
        paths=paths,
        runner=runner,
        on_device=on_device,
    )
    for candidate, collected in probing.readings:
        seen.add((candidate.name, candidate.type))
        found.append(
            _examine(
                candidate, config, block_devices, paths=paths, runner=runner, collected=collected
            )
        )
    for candidate in manual_candidates(config.discovery.devices):
        found.append(
            _read_or_skip(
                candidate,
                config,
                block_devices,
                seen,
                paths=paths,
                runner=runner,
                on_device=on_device,
            )
        )

    version = scan.smartctl_version or next(
        (item.collected.smartctl_version for item in found if item.collected is not None), ()
    )
    return Discovery(
        devices=_deduplicate(found),
        smartctl_version=version,
        scan_error=scan.error,
        enrichment_error=block_devices.error,
        scsi_hosts=scsi_hosts,
        probe=probing,
    )


def _read_or_skip(
    candidate: Candidate,
    config: Config,
    block_devices: BlockDevices,
    seen: set[tuple[str, str]],
    *,
    paths: HostPaths,
    runner: ProcessRunner,
    on_device: Callable[[Candidate], None] | None,
) -> Found:
    """Read one candidate, or report it as a device that was already found."""
    if (candidate.name, candidate.type) in seen:
        return Found(
            candidate,
            Outcome.SKIPPED,
            reason=SkipReason.DUPLICATE,
            detail="listed twice",
        )
    seen.add((candidate.name, candidate.type))
    if on_device is not None:
        on_device(candidate)
    return _examine(candidate, config, block_devices, paths=paths, runner=runner)


def _examine(
    candidate: Candidate,
    config: Config,
    block_devices: BlockDevices,
    *,
    paths: HostPaths,
    runner: ProcessRunner,
    collected: Collected | None = None,
) -> Found:
    """Return what one device is, reading it unless it is skipped before.

    `collected` is the answer of a read that happened already, which is how a
    device of the probe reaches this examination without a second call.
    """
    if not candidate.valid:
        return Found(
            candidate,
            Outcome.UNREADABLE,
            detail="the name or the type has a form that is not passed to smartctl",
        )

    details = details_of(candidate.name, block_devices, paths, device_type=candidate.type)
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
    volume = _volume_before_reading(candidate, details)
    if volume is not None:
        return Found(
            candidate,
            Outcome.SKIPPED,
            reason=SkipReason.LOGICAL_VOLUME,
            detail=volume,
            details=details,
        )

    if collected is None:
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
    skipped = _not_a_drive(collected.document, candidate)
    if skipped is not None:
        reason, detail = skipped
        return Found(
            candidate,
            Outcome.SKIPPED,
            collected=collected,
            reason=reason,
            detail=detail,
            details=details,
        )

    try:
        snapshot = parse(
            collected.document,
            access=DeviceAccess(
                candidate.name,
                candidate.type,
                candidate.protocol or protocol_of(collected.document) or "",
            ),
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

    # A per-drive override can name another detail level, which is known only
    # after the drive was read: an override has it read once more (FR-403).
    override = drive_override(config, snapshot.identity)
    if (
        override is not None
        and override.detail is not None
        and override.detail is not config.smartctl.detail
    ):
        again = _read_again(
            candidate, replace(config.smartctl, detail=override.detail), details, runner=runner
        )
        if again is not None:
            snapshot, collected = again

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
    if override is not None and override.exclude:
        return Found(
            candidate,
            Outcome.SKIPPED,
            snapshot=snapshot,
            collected=collected,
            reason=SkipReason.EXCLUDED,
            detail=f"{override.selector.describe()}, per-drive override",
            details=details,
        )
    return Found(
        candidate, Outcome.MONITORED, snapshot=snapshot, collected=collected, details=details
    )


def _volume_before_reading(candidate: Candidate, details: Details) -> str | None:
    """Return the signal that names a device a logical volume before it is read (ADR 0028).

    The vendor and model of lsblk come first, then the `open_error` of the
    scan. The inquiry data count only for the node itself, not for a drive
    behind a controller (ADR 0034).
    """
    if logical_volume(details.vendor, details.model):
        return "lsblk " + inquiry_text(details.vendor, details.model, product_label="model")
    if asks_for_megaraid(candidate.open_error):
        return "the scan: smartctl asks for -d megaraid,N"
    return None


def _not_a_drive(
    document: Mapping[str, object], candidate: Candidate
) -> tuple[SkipReason, str] | None:
    """Return why a device read as SCSI is not a drive, from its inquiry data (ADR 0028).

    Vendor and product name a logical volume; the peripheral device type
    names an enclosure (13) or a controller (12). Another protocol passes.
    """
    if (protocol_of(document) or candidate.protocol) != "SCSI":
        return None
    inquiry = inquiry_of(document)
    if logical_volume(inquiry.vendor, inquiry.product):
        named = inquiry_text(inquiry.vendor, inquiry.product, product_label="product")
        return SkipReason.LOGICAL_VOLUME, f"the inquiry data of the drive output: {named}"
    kind = inquiry.peripheral_type
    if kind is not None and kind not in DISK_TYPES:
        name = f", {' '.join(inquiry.peripheral_name.split())}" if inquiry.peripheral_name else ""
        return SkipReason.NOT_A_DISK, f"SCSI peripheral device type {kind}{name}"
    return None


def _read_again(
    candidate: Candidate,
    settings: SmartctlSettings,
    details: Details,
    *,
    runner: ProcessRunner,
) -> tuple[Snapshot, Collected] | None:
    """Read a device once more with other settings; `None` when that brought nothing."""
    again = collect_drive(
        candidate.name,
        candidate.type,
        settings=settings,
        protocol=candidate.protocol,
        runner=runner,
    )
    if again.status is not Status.OK or again.document is None:
        return None
    try:
        parsed = parse(
            again.document,
            access=DeviceAccess(
                candidate.name,
                candidate.type,
                candidate.protocol or protocol_of(again.document) or "",
            ),
            collection=Collection(
                smartctl_version=again.smartctl_version,
                exit_status=again.exit_status or 0,
                messages=again.messages,
                duration_seconds=again.duration_seconds,
            ),
        )
    except ParseError:
        return None
    return replace(parsed, location=details.location, membership=details.membership), again


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
