# SPDX-License-Identifier: AGPL-3.0-or-later
"""The catalog of checks and the evaluation of one snapshot (ADR 0010).

Each check has a stable identifier, its drive classes, the value it reads, its
kind and its default thresholds; docs/check-catalog.md is the living list. A
missing input is not applicable (FR-206); the planner raises drive.missing and
drive.unreadable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pve_smart_alert.model import (
    CheckKind,
    DriveClass,
    FailingAttribute,
    Finding,
    Severity,
    Snapshot,
    WearSource,
    behind_controller,
)

__all__ = [
    "ALL_CLASSES",
    "ASSUMED_SPARE_THRESHOLD",
    "ATA_CLASSES",
    "CATALOG",
    "Check",
    "EffectiveCheck",
    "Thresholds",
    "Worsening",
    "counters",
    "default_checks",
    "evaluate",
]

# Every drive class (docs/check-catalog.md).
ALL_CLASSES: Final = frozenset(DriveClass)
# The classes `hdd` and `ssd`, which cover SATA, SAS and parallel SCSI drives;
# the name is narrower than that.
ATA_CLASSES: Final = frozenset({DriveClass.HDD, DriveClass.SSD})

# The NVMe Critical Warning byte, bit by bit (docs/check-catalog.md).
_SPARE_BELOW: Final = 0
_TEMPERATURE_EXCEEDED: Final = 1
_RELIABILITY_DEGRADED: Final = 2
_READ_ONLY: Final = 3
_BACKUP_FAILED: Final = 4
_PMR_UNRELIABLE: Final = 5

# The spare threshold a drive is assumed to have when it reports none
# (docs/check-catalog.md).
ASSUMED_SPARE_THRESHOLD: Final = 10

# The rank of a severity, for comparing severities of one check.
_RANK: Final[Mapping[Severity, int]] = {
    Severity.NOTICE: 1,
    Severity.WARNING: 2,
    Severity.CRITICAL: 3,
}


class Worsening(StrEnum):
    """What counts as worse for a condition that stays at its severity (ADR 0009).

    For defect and error counters every increase, reported subject to the
    cool-down; for gauges such as temperature and wear only a rise to a
    higher severity, which is an escalation.
    """

    INCREASE = "increase"
    ESCALATION = "escalation"


@dataclass(frozen=True)
class Thresholds:
    """The thresholds of a check, one per severity (ADR 0010).

    `None` means the severity is not used by default. All three can be set
    in the configuration, whatever the default is (FR-402).
    """

    notice: int | None = None
    warning: int | None = None
    critical: int | None = None


@dataclass(frozen=True)
class Check:
    """One check of the catalog (docs/check-catalog.md).

    `severity` is fixed for a flag check, `thresholds` and `per_class` hold
    the defaults, and `slots` the keys the configuration may set; `settable`
    adds the confirmation count (ADR 0011).
    """

    id: str
    classes: frozenset[DriveClass]
    kind: CheckKind
    source: str
    severity: Severity | None = None
    thresholds: Thresholds | None = None
    per_class: Mapping[DriveClass, Thresholds] | None = None
    enabled: bool = True
    slots: frozenset[str] = frozenset({"enabled"})
    metric: str = ""
    unit: str = ""
    # Whether a threshold is met above its value and not at it: up to 100
    # command timeouts are what clean drives show (ADR 0010).
    strictly_above: bool = False
    # In how many runs in a row a condition has to be seen before it is
    # notified (ADR 0009). Temperature needs two (FR-308).
    confirm_runs: int = 1
    # What counts as worse at the same severity (docs/check-catalog.md).
    worsening: Worsening | None = None
    # Whether the configuration may set a confirmation count. The checks
    # that the planner raises from presence count runs of their own
    # (`notify.missing_runs`, `notify.unreadable_runs`).
    confirmable: bool = True

    @property
    def settable(self) -> frozenset[str]:
        """The keys the configuration may set for this check (ADR 0011).

        A condition takes its confirmation count as well; an event has none,
        because an increase is reported when it is seen (ADR 0009).
        """
        if self.kind is CheckKind.CONDITION and self.confirmable:
            return self.slots | {"confirm_runs"}
        return self.slots


@dataclass(frozen=True)
class EffectiveCheck:
    """The settings of one check as they apply to one drive (ARCHITECTURE.md section 6).

    For `nvme.spare` the warning threshold is the margin above the threshold
    of the drive itself (docs/check-catalog.md).
    """

    check: Check
    enabled: bool
    thresholds: Thresholds | None = None
    confirm_runs: int = 1


# The temperature limits per class, provisional until Q-T4 is answered. A
# finding needs confirmation in two consecutive runs (FR-308).
TEMPERATURE_LIMITS: Final[Mapping[DriveClass, Thresholds]] = {
    DriveClass.HDD: Thresholds(warning=50, critical=60),
    DriveClass.SSD: Thresholds(warning=60, critical=70),
    DriveClass.NVME: Thresholds(warning=70, critical=80),
}

_THREE_SLOTS: Final = frozenset({"enabled", "notice", "warning", "critical"})

# The catalog, by the stable identifier of each check.
CATALOG: Final[Mapping[str, Check]] = {
    check.id: check
    for check in (
        # All drives (docs/check-catalog.md, "All drives"). Do not apply
        # health.failed or smart.disabled to NVMe: its Critical Warning bits are
        # checked instead (docs/check-catalog.md).
        Check(
            "health.failed",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "the health verdict of the drive",
            severity=Severity.CRITICAL,
        ),
        Check(
            "selftest.failed",
            ALL_CLASSES,
            CheckKind.CONDITION,
            "the most recent self-test in the log",
            severity=Severity.WARNING,
        ),
        Check(
            "temperature",
            ALL_CLASSES,
            CheckKind.CONDITION,
            "the current temperature",
            per_class=TEMPERATURE_LIMITS,
            slots=_THREE_SLOTS,
            metric="temperature.current",
            unit="°C",
            confirm_runs=2,
            worsening=Worsening.ESCALATION,
        ),
        Check(
            "wear",
            frozenset({DriveClass.SSD, DriveClass.NVME}),
            CheckKind.CONDITION,
            "the percentage of the rated endurance used",
            thresholds=Thresholds(notice=80, warning=95),
            slots=_THREE_SLOTS,
            metric="wear.percent_used",
            unit="%",
            worsening=Worsening.ESCALATION,
        ),
        Check(
            "smart.disabled",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "SMART available but switched off",
            severity=Severity.NOTICE,
        ),
        # Raised by the planner from the presence of a drive, not from a
        # snapshot (FR-309, FR-310).
        Check(
            "drive.unreadable",
            ALL_CLASSES,
            CheckKind.CONDITION,
            "no usable SMART data in consecutive runs",
            severity=Severity.WARNING,
            confirmable=False,
        ),
        Check(
            "drive.missing",
            ALL_CLASSES,
            CheckKind.EVENT,
            "a known drive absent in consecutive runs",
            severity=Severity.WARNING,
        ),
        # SATA (docs/check-catalog.md, "SATA (ATA attributes)"). The counter
        # checks read raw values: the normalized value is a vendor scale that
        # falls with wear, while the raw value is the total that is counted.
        Check(
            "ata.attribute_failing",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "an ATA attribute at or below its vendor threshold, except temperature attributes",
            # Without a fixed severity: the evaluator decides by the kind of
            # the attribute, an old-age attribute is a warning and a pre-fail
            # attribute a critical finding (docs/check-catalog.md).
            severity=None,
        ),
        Check(
            "ata.reallocated_sectors",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "attribute 5, raw",
            thresholds=Thresholds(notice=1, warning=5, critical=70),
            slots=_THREE_SLOTS,
            metric="ata.attr.5.raw",
            unit="sectors",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "ata.reported_uncorrectable",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "attribute 187, raw",
            thresholds=Thresholds(warning=1, critical=20),
            slots=_THREE_SLOTS,
            metric="ata.attr.187.raw",
            unit="errors",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "ata.command_timeouts",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "attribute 188, raw, decoded",
            thresholds=Thresholds(warning=100),
            slots=_THREE_SLOTS,
            metric="ata.command_timeouts",
            unit="timeouts",
            strictly_above=True,
            worsening=Worsening.ESCALATION,
        ),
        Check(
            "ata.pending_sectors",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "attribute 197, raw",
            thresholds=Thresholds(warning=1, critical=16),
            slots=_THREE_SLOTS,
            metric="ata.attr.197.raw",
            unit="sectors",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "ata.offline_uncorrectable",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "attribute 198, raw",
            thresholds=Thresholds(warning=1, critical=10),
            slots=_THREE_SLOTS,
            metric="ata.attr.198.raw",
            unit="sectors",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "ata.spin_retries",
            frozenset({DriveClass.HDD}),
            CheckKind.CONDITION,
            "attribute 10, raw",
            thresholds=Thresholds(warning=1),
            slots=_THREE_SLOTS,
            metric="ata.attr.10.raw",
            unit="retries",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "ata.end_to_end_errors",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "attribute 184, raw",
            thresholds=Thresholds(warning=1),
            slots=_THREE_SLOTS,
            metric="ata.attr.184.raw",
            unit="errors",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "ata.crc_errors",
            ATA_CLASSES,
            CheckKind.EVENT,
            "attribute 199, raw, against the baseline",
            severity=Severity.NOTICE,
            metric="ata.attr.199.raw",
        ),
        Check(
            "ata.error_log",
            ATA_CLASSES,
            CheckKind.EVENT,
            "the number of entries in the ATA error log, against the baseline",
            severity=Severity.NOTICE,
            metric="ata.error_log.count",
        ),
        # NVMe (docs/check-catalog.md, "NVMe").
        Check(
            "nvme.spare",
            frozenset({DriveClass.NVME}),
            CheckKind.CONDITION,
            "the available spare against the threshold of the drive",
            thresholds=Thresholds(warning=15),
            slots=frozenset({"enabled", "warning"}),
            metric="nvme.available_spare",
            unit="%",
            worsening=Worsening.ESCALATION,
        ),
        Check(
            "nvme.reliability_degraded",
            frozenset({DriveClass.NVME}),
            CheckKind.CONDITION,
            "Critical Warning bit 2",
            severity=Severity.CRITICAL,
        ),
        Check(
            "nvme.read_only",
            frozenset({DriveClass.NVME}),
            CheckKind.CONDITION,
            "Critical Warning bit 3",
            severity=Severity.CRITICAL,
        ),
        Check(
            "nvme.backup_failed",
            frozenset({DriveClass.NVME}),
            CheckKind.CONDITION,
            "Critical Warning bit 4",
            severity=Severity.CRITICAL,
        ),
        Check(
            "nvme.pmr_unreliable",
            frozenset({DriveClass.NVME}),
            CheckKind.CONDITION,
            "Critical Warning bit 5",
            severity=Severity.WARNING,
        ),
        Check(
            "nvme.media_errors",
            frozenset({DriveClass.NVME}),
            CheckKind.CONDITION,
            "media and data integrity errors",
            thresholds=Thresholds(warning=1),
            slots=_THREE_SLOTS,
            metric="nvme.media_errors",
            unit="errors",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "nvme.thermal_excursion",
            frozenset({DriveClass.NVME}),
            CheckKind.EVENT,
            "the time above the critical temperature, against the baseline",
            severity=Severity.WARNING,
            metric="nvme.critical_temperature_minutes",
        ),
        Check(
            "nvme.error_log",
            frozenset({DriveClass.NVME}),
            CheckKind.EVENT,
            "the number of error log entries, against the baseline",
            severity=Severity.NOTICE,
            # Many drives log harmless entries, and reading the log can add
            # entries on some drives with smartmontools 7.4
            # (docs/check-catalog.md).
            enabled=False,
            metric="nvme.error_log_entries",
        ),
        # SAS and parallel SCSI (docs/check-catalog.md, "SAS (SCSI log
        # pages)"), read by `parsers/scsi.py`.
        Check(
            "scsi.grown_defects",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "the elements of the grown defect list",
            thresholds=Thresholds(notice=1, warning=100),
            slots=_THREE_SLOTS,
            metric="scsi.grown_defects",
            unit="defects",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "scsi.uncorrected_errors",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "the sum of uncorrected read, write and verify errors",
            thresholds=Thresholds(warning=1),
            slots=_THREE_SLOTS,
            metric="scsi.uncorrected_errors",
            unit="errors",
            worsening=Worsening.INCREASE,
        ),
        Check(
            "scsi.pending_defects",
            ATA_CLASSES,
            CheckKind.CONDITION,
            "the pending defects",
            thresholds=Thresholds(warning=1),
            slots=_THREE_SLOTS,
            metric="scsi.pending_defects",
            unit="defects",
            worsening=Worsening.INCREASE,
        ),
    )
}


def default_checks(drive_class: DriveClass) -> dict[str, EffectiveCheck]:
    """Return the settings of every check for one class, with the built-in defaults."""
    return {
        check.id: EffectiveCheck(
            check=check,
            enabled=check.enabled,
            thresholds=(check.per_class or {}).get(drive_class, check.thresholds),
            confirm_runs=check.confirm_runs,
        )
        for check in CATALOG.values()
    }


def evaluate(
    snapshot: Snapshot,
    settings: Mapping[str, EffectiveCheck] | None = None,
    baselines: Mapping[str, int] | None = None,
) -> list[Finding]:
    """Evaluate one snapshot and return what the checks found (FR-301).

    `settings` are the effective checks of this drive, `baselines` those of
    its event counters. A check that is disabled, does not apply or has no
    input returns nothing (FR-206); an event without a baseline returns
    nothing (FR-306). The findings are in catalog order.
    """
    findings: list[Finding] = []
    for item in _applicable(snapshot, settings):
        check = item.check
        if check.kind is CheckKind.EVENT:
            finding = _event(snapshot, item, baselines or {})
        else:
            evaluator = _EVALUATORS.get(check.id)
            finding = evaluator(snapshot, item) if evaluator is not None else None
        if finding is not None:
            findings.append(finding)
    return findings


def counters(
    snapshot: Snapshot, settings: Mapping[str, EffectiveCheck] | None = None
) -> dict[str, int]:
    """Return the current value of every enabled event counter the drive reports.

    The planner records them as baselines when a drive is first seen, and
    lowers a baseline that a counter has fallen below (ADR 0009).
    """
    result = {}
    for item in _applicable(snapshot, settings):
        if item.check.kind is not CheckKind.EVENT or not item.check.metric:
            continue
        value = snapshot.metrics.get(item.check.metric)
        if value is not None:
            result[item.check.id] = value
    return result


def _applicable(
    snapshot: Snapshot, settings: Mapping[str, EffectiveCheck] | None
) -> list[EffectiveCheck]:
    """Return the enabled checks that apply to the class of the drive, in catalog order."""
    effective = settings if settings is not None else default_checks(snapshot.drive_class)
    return [
        item
        for name, item in effective.items()
        if name in CATALOG and item.enabled and snapshot.drive_class in item.check.classes
    ]


# What one check returns for one snapshot: one finding, or nothing.
_Evaluator = Callable[[Snapshot, EffectiveCheck], "Finding | None"]


def _finding(
    item: EffectiveCheck,
    severity: Severity,
    text: str,
    *,
    value: int | None = None,
    threshold: int | None = None,
) -> Finding:
    check = item.check
    return Finding(
        check=check.id,
        kind=check.kind,
        severity=severity,
        text=text,
        value=value,
        threshold=threshold,
    )


def _flag(item: EffectiveCheck, text: str, *, value: int | None = None) -> Finding:
    """Return the finding of a flag check with its fixed severity."""
    return _finding(item, item.check.severity or Severity.NOTICE, text, value=value)


def _exceeded(item: EffectiveCheck, value: int) -> tuple[Severity, int] | None:
    """Return the highest severity whose threshold is met, with that threshold."""
    thresholds = item.thresholds
    if thresholds is None:
        return None
    for severity, threshold in (
        (Severity.CRITICAL, thresholds.critical),
        (Severity.WARNING, thresholds.warning),
        (Severity.NOTICE, thresholds.notice),
    ):
        if threshold is None:
            continue
        meets = value > threshold if item.check.strictly_above else value >= threshold
        if meets:
            return severity, threshold
    return None


def _counter(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    """Evaluate a threshold check that reads one metric of the snapshot."""
    value = snapshot.metrics.get(item.check.metric)
    if value is None:
        return None
    exceeded = _exceeded(item, value)
    if exceeded is None:
        return None
    severity, threshold = exceeded
    how = "above" if item.check.strictly_above else "at or above"
    return _finding(
        item,
        severity,
        f"{value} {item.check.unit}, {how} the {severity.value} threshold of {threshold}",
        value=value,
        threshold=threshold,
    )


def _health(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    if snapshot.health_passed is False:
        detail = f": {snapshot.health_detail}" if snapshot.health_detail else ""
        return _flag(item, f"the drive reports its health as failed{detail}")
    return None


def _self_test(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    if snapshot.last_self_test_passed is False:
        return _flag(item, "the most recent self-test in the log ended with an error")
    return None


def _smart_disabled(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    if snapshot.smart_available is True and snapshot.smart_enabled is False:
        # The tool never enables SMART itself (FR-311, ADR 0012); it names the
        # command. A drive behind a controller is addressed with its type, or
        # the command would reach the node (ADR 0034).
        access = snapshot.access
        device = f"-d {access.type} " if behind_controller(access.type) else ""
        command = f"smartctl -s on {device}{access.name}"
        if snapshot.access.protocol == "SCSI":
            # For a SCSI drive SMART is its informational exceptions, without
            # which it reports no failing health (Research 08).
            return _flag(
                item,
                "the informational exceptions are switched off, so the drive reports"
                f" no failing health; they can be turned on with: {command}",
            )
        return _flag(item, f"SMART is switched off; it can be turned on with: {command}")
    return None


def _temperature(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    value = snapshot.metrics.get("temperature.current")
    if value is None:
        return None
    exceeded = _exceeded(item, value)
    # Critical Warning bit 1 raises the temperature at least to a warning
    # (docs/check-catalog.md).
    if _bit(snapshot, _TEMPERATURE_EXCEEDED) and (
        exceeded is None or _RANK[exceeded[0]] < _RANK[Severity.WARNING]
    ):
        return _finding(
            item,
            Severity.WARNING,
            f"{value} °C; the drive reports a temperature above its own limit"
            f" (Critical Warning bit {_TEMPERATURE_EXCEEDED})",
            value=value,
        )
    if exceeded is None:
        return None
    severity, threshold = exceeded
    return _finding(
        item,
        severity,
        f"{value} °C, at or above the {severity.value} limit of {threshold} °C",
        value=value,
        threshold=threshold,
    )


def _wear(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    value = snapshot.metrics.get("wear.percent_used")
    if value is None:
        return None
    exceeded = _exceeded(item, value)
    if exceeded is None:
        return None
    severity, threshold = exceeded
    # The source of the value is part of the finding, so that the difference
    # to the web interface is explained where the number is seen (ADR 0021).
    source = snapshot.wear_source or WearSource.ENDURANCE_USED
    return _finding(
        item,
        severity,
        f"{value} % of the rated endurance used, from {source.value};"
        f" at or above the {severity.value} threshold of {threshold} %",
        value=value,
        threshold=threshold,
    )


def _attribute_failing(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    failing = tuple(
        attribute
        for attribute in snapshot.failing_attributes
        if not _temperature_attribute(attribute)
    )
    if not failing:
        return None
    names = ", ".join(f"{attribute.id} ({attribute.name})" for attribute in failing)
    if any(attribute.prefailure for attribute in failing):
        return _finding(
            item,
            Severity.CRITICAL,
            f"pre-fail attributes at or below their vendor threshold: {names}",
        )
    return _finding(
        item, Severity.WARNING, f"old-age attributes at or below their vendor threshold: {names}"
    )


def _temperature_attribute(attribute: FailingAttribute) -> bool:
    """Whether an attribute is a temperature attribute, which is excluded here.

    The rule is heuristic: 190 and 194 are the temperature on every drive seen
    so far (Research 02, Research 06), and the name catches a vendor id.
    """
    return "temp" in attribute.name.lower() or attribute.id in (190, 194)


def _bit(snapshot: Snapshot, bit: int) -> bool:
    warning = snapshot.nvme_critical_warning
    return warning is not None and bool(warning & (1 << bit))


def _spare(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    spare = snapshot.metrics.get("nvme.available_spare")
    if spare is None:
        return None
    limit = snapshot.metrics.get("nvme.available_spare_threshold")
    if limit is None:
        limit = ASSUMED_SPARE_THRESHOLD
    if _bit(snapshot, _SPARE_BELOW) or spare <= limit:
        return _finding(
            item,
            Severity.CRITICAL,
            f"available spare {spare} %, at or below the threshold of the drive, {limit} %",
            value=spare,
            threshold=limit,
        )
    # The margin is the warning threshold of the check; a configured 0 is a
    # configured 0, not the default (FR-402).
    margin = item.thresholds.warning if item.thresholds is not None else None
    if margin is None:
        # Keep in sync with the default warning threshold of `nvme.spare` in CATALOG.
        margin = 15
    if spare <= limit + margin:
        return _finding(
            item,
            Severity.WARNING,
            f"available spare {spare} %, within {margin} points of the threshold of the"
            f" drive, {limit} %",
            value=spare,
            threshold=limit + margin,
        )
    return None


def _critical_warning_bit(bit: int, text: str) -> _Evaluator:
    def evaluator(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
        return _flag(item, text) if _bit(snapshot, bit) else None

    return evaluator


def _event(
    snapshot: Snapshot, item: EffectiveCheck, baselines: Mapping[str, int]
) -> Finding | None:
    """Return the rise of a cumulative counter above its baseline (FR-306).

    Without a baseline there is nothing to compare: the planner records the
    current value as the baseline, and a counter that was already high when
    the drive was first seen never alerts.
    """
    check = item.check
    value = snapshot.metrics.get(check.metric) if check.metric else None
    baseline = baselines.get(check.id)
    if value is None or baseline is None or value <= baseline:
        return None
    return _flag(item, f"{_EVENT_NAMES[check.id]} rose from {baseline} to {value}", value=value)


# How an event names its counter in a finding.
_EVENT_NAMES: Final[Mapping[str, str]] = {
    "ata.crc_errors": "the interface CRC errors (attribute 199)",
    "ata.error_log": "the entries of the ATA error log",
    "nvme.thermal_excursion": "the minutes above the critical temperature",
    "nvme.error_log": "the entries of the NVMe error log",
}


_EVALUATORS: Final[Mapping[str, _Evaluator]] = {
    "health.failed": _health,
    "selftest.failed": _self_test,
    "smart.disabled": _smart_disabled,
    "temperature": _temperature,
    "wear": _wear,
    "ata.attribute_failing": _attribute_failing,
    "ata.reallocated_sectors": _counter,
    "ata.reported_uncorrectable": _counter,
    "ata.command_timeouts": _counter,
    "ata.pending_sectors": _counter,
    "ata.offline_uncorrectable": _counter,
    "ata.spin_retries": _counter,
    "ata.end_to_end_errors": _counter,
    "nvme.spare": _spare,
    "nvme.reliability_degraded": _critical_warning_bit(
        _RELIABILITY_DEGRADED, "the drive reports its reliability as degraded"
    ),
    "nvme.read_only": _critical_warning_bit(_READ_ONLY, "the drive reports itself as read-only"),
    "nvme.backup_failed": _critical_warning_bit(
        _BACKUP_FAILED, "the drive reports that its volatile memory backup device failed"
    ),
    "nvme.pmr_unreliable": _critical_warning_bit(
        _PMR_UNRELIABLE, "the drive reports its persistent memory region as unreliable"
    ),
    "nvme.media_errors": _counter,
    "scsi.grown_defects": _counter,
    "scsi.uncorrected_errors": _counter,
    "scsi.pending_defects": _counter,
}
