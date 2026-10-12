# SPDX-License-Identifier: AGPL-3.0-or-later
"""The catalog of checks and the evaluation of one snapshot (ADR 0010).

Each check has a stable identifier, the drive classes it applies to, the
value it reads from the snapshot, its kind and its default thresholds; the
living list with the reasoning behind every number is
[docs/check-catalog.md](../../docs/check-catalog.md). A check whose input is
missing is not applicable and returns nothing: missing data is never a
finding (FR-206). Of a threshold check the highest severity whose threshold
is met is reported (FR-302, FR-304). The drive's own failure verdict is
always critical (FR-303); wear is never critical by default (FR-307).

The settings of a check as they apply to one drive, `EffectiveCheck`, are
resolved by `pve_smart_alert.config`: built-in default, overridden by the
global configuration, overridden by the first matching per-drive override
(ARCHITECTURE.md section 6).

Event checks compare a cumulative counter with the baseline of the state
file, which arrives with milestone M4; until then they return nothing
(FR-306). The same holds for drives that are missing or unreadable in
consecutive runs and for the conditions of the tool itself: their checks are
not in this catalog until state exists to answer them.
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
    "default_checks",
    "evaluate",
]

#: Every drive class (docs/check-catalog.md).
ALL_CLASSES: Final = frozenset(DriveClass)
#: SATA and SAS drives, which the classes `hdd` and `ssd` cover.
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

    `severity` is the fixed severity of a flag check; `thresholds` the
    defaults of a threshold check; `per_class` the defaults of the one check
    whose thresholds differ per drive class. `slots` are the keys the
    configuration may set for this check (ADR 0011). `source` names what the
    check reads, for messages and for the reference of the configuration.
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

    @property
    def settable(self) -> frozenset[str]:
        """The keys the configuration may set for this check (ADR 0011).

        A condition takes its confirmation count as well; an event has none,
        because an increase is reported when it is seen (ADR 0009).
        """
        if self.kind is CheckKind.CONDITION:
            return self.slots | {"confirm_runs"}
        return self.slots


@dataclass(frozen=True)
class EffectiveCheck:
    """The settings of one check as they apply to one drive (ARCHITECTURE.md section 6).

    For the one check whose thresholds differ per class, `thresholds` holds
    the ones of the drive's class. For `nvme.spare` the warning threshold is
    the margin in points above the threshold of the drive itself
    (docs/check-catalog.md).
    """

    check: Check
    enabled: bool
    thresholds: Thresholds | None = None
    confirm_runs: int = 1


# The temperature limits per class. A finding needs confirmation in two
# consecutive runs before the first notification (FR-308), which the
# notification planner counts.
TEMPERATURE_LIMITS: Final[Mapping[DriveClass, Thresholds]] = {
    DriveClass.HDD: Thresholds(warning=50, critical=60),
    DriveClass.SSD: Thresholds(warning=60, critical=70),
    DriveClass.NVME: Thresholds(warning=70, critical=80),
}

_THREE_SLOTS: Final = frozenset({"enabled", "notice", "warning", "critical"})

#: The catalog: every check of milestone M3 and later, by its stable identifier.
CATALOG: Final[Mapping[str, Check]] = {
    check.id: check
    for check in (
        # All drives (docs/check-catalog.md, "All drives"). The checks for
        # drives that are missing or unreadable in consecutive runs need the
        # state of milestone M4 and are not here yet.
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
        # SATA (docs/check-catalog.md, "SATA (ATA attributes)").
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
        ),
        Check(
            "ata.error_log",
            ATA_CLASSES,
            CheckKind.EVENT,
            "the number of entries in the ATA error log, against the baseline",
            severity=Severity.NOTICE,
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
        ),
        # SAS (docs/check-catalog.md, "SAS (SCSI log pages)"). No parser
        # produces these metrics until milestone M6; the checks exist so
        # that their identifiers are stable from now on.
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
    snapshot: Snapshot, settings: Mapping[str, EffectiveCheck] | None = None
) -> list[Finding]:
    """Evaluate one snapshot and return what the checks found (FR-301).

    `settings` are the effective checks for this drive, as
    `pve_smart_alert.config.effective_checks` resolves them; without them the
    built-in defaults apply. A check that is disabled, that does not apply
    to the class of the drive, or whose input is missing, returns nothing.
    The findings are in the order of the catalog.
    """
    effective = settings if settings is not None else default_checks(snapshot.drive_class)
    findings: list[Finding] = []
    for name, item in effective.items():
        check = CATALOG.get(name)
        if check is None or not item.enabled:
            continue
        if snapshot.drive_class not in check.classes:
            continue
        finding = _EVALUATORS[check.id](snapshot, item)
        if finding is not None:
            findings.append(finding)
    return findings


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
        return _flag(item, "the drive reports its health as failed")
    return None


def _self_test(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    if snapshot.last_self_test_passed is False:
        return _flag(item, "the most recent self-test in the log ended with an error")
    return None


def _smart_disabled(snapshot: Snapshot, item: EffectiveCheck) -> Finding | None:
    if snapshot.smart_available is True and snapshot.smart_enabled is False:
        # The tool never enables SMART itself (FR-311, ADR 0012); it names
        # the command an administrator can use.
        command = f"smartctl -s on {snapshot.access.name}"
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

    The rule is heuristic, in this order of strength: the two standard
    attributes 190 and 194 are the temperature on every drive seen so far,
    and the name is checked as well so that an attribute of a vendor that
    reports the temperature on an id of its own is still excluded. The
    exclusion exists because temperature attributes are the well-known
    source of false findings (docs/check-catalog.md, Research 03).
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


def _event(_snapshot: Snapshot, _item: EffectiveCheck) -> Finding | None:
    """Return nothing: an event needs the baseline of the state file (FR-306)."""
    return None


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
    "ata.crc_errors": _event,
    "ata.error_log": _event,
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
    "nvme.thermal_excursion": _event,
    "nvme.error_log": _event,
    "scsi.grown_defects": _counter,
    "scsi.uncorrected_errors": _counter,
    "scsi.pending_defects": _counter,
}
