# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parser for ATA drives: SATA hard disks and SSDs (ADR 0004).

The wear value and its source follow ADR 0021 (`wear.py`). The metrics of
the attribute table are `ata.attr.ID.raw` and
`ata.attr.ID.value`. The checks read the raw value only of the attributes
the catalog names; raw values of other attributes are packed on some drives
(docs/check-catalog.md). The temperature comes from `temperature.current`,
never from the raw value of attribute 194, which the Fanxiang S301 of the
test cluster packs (Research 06).
"""

from __future__ import annotations

from collections.abc import Mapping

from pve_smart_alert.model import (
    Collection,
    DeviceAccess,
    DriveClass,
    FailingAttribute,
    Snapshot,
)
from pve_smart_alert.parsers.common import (
    capacity_of,
    entries,
    flag,
    identity_of,
    integer,
    put,
    section,
    text,
)
from pve_smart_alert.parsers.wear import WEAR_METRIC, WEB_INTERFACE_METRIC, ata_wear


def parse(
    document: Mapping[str, object], *, access: DeviceAccess, collection: Collection
) -> Snapshot:
    """Return the snapshot of the output of smartctl for one ATA drive."""
    support = section(document, "smart_support")
    wear = ata_wear(document)
    metrics: dict[str, int] = {}
    put(metrics, WEAR_METRIC, wear.percent_used)
    put(metrics, WEB_INTERFACE_METRIC, wear.web_interface)
    put(metrics, "temperature.current", integer(section(document, "temperature"), "current"))
    put(metrics, "ata.error_log.count", _error_log_count(document))
    for attribute in entries(document, "ata_smart_attributes", "table"):
        number = integer(attribute, "id")
        if number is None:
            continue
        put(metrics, f"ata.attr.{number}.value", integer(attribute, "value"))
        put(metrics, f"ata.attr.{number}.raw", integer(section(attribute, "raw"), "value"))

    return Snapshot(
        identity=identity_of(document, wwn=wwn_of(document)),
        access=access,
        drive_class=drive_class_of(document),
        collection=collection,
        firmware=text(document, "firmware_version"),
        capacity_bytes=capacity_of(document),
        smart_available=flag(support, "available"),
        smart_enabled=flag(support, "enabled"),
        health_passed=flag(section(document, "smart_status"), "passed"),
        failing_attributes=_failing(document),
        last_self_test_passed=_last_self_test(document),
        power_on_hours=integer(section(document, "power_on_time"), "hours"),
        power_cycles=integer(document, "power_cycle_count"),
        metrics=metrics,
        wear_source=wear.source,
    )


def drive_class_of(document: Mapping[str, object]) -> DriveClass:
    """Return `ssd` for a rotation rate of 0, else `hdd`, also when it is unknown.

    smartctl writes 0 for a drive that reports itself as solid state; an
    unknown rate counts as a hard disk (docs/check-catalog.md).
    """
    return DriveClass.SSD if integer(document, "rotation_rate") == 0 else DriveClass.HDD


def wwn_of(document: Mapping[str, object]) -> str | None:
    """Return the WWN as 16 hexadecimal digits, from its parts in the JSON."""
    wwn = section(document, "wwn")
    naa, oui, number = integer(wwn, "naa"), integer(wwn, "oui"), integer(wwn, "id")
    if naa is None or oui is None or number is None:
        return None
    return f"{(naa << 60) | (oui << 36) | number:016x}"


def _failing(document: Mapping[str, object]) -> tuple[FailingAttribute, ...]:
    """Return the attributes whose value is at or below their threshold now.

    smartctl marks them with `when_failed` "now". A threshold of 0 never
    fails, so attribute 187 of the Fanxiang S301 with the worst value 0 and
    the threshold 0 is not among them (Research 06).
    """
    failing: list[FailingAttribute] = []
    for attribute in entries(document, "ata_smart_attributes", "table"):
        number = integer(attribute, "id")
        if number is not None and text(attribute, "when_failed") == "now":
            failing.append(
                FailingAttribute(
                    id=number,
                    name=text(attribute, "name") or "",
                    prefailure=flag(section(attribute, "flags"), "prefailure") is True,
                )
            )
    return tuple(failing)


def _last_self_test(document: Mapping[str, object]) -> bool | None:
    """Return whether the most recent self-test of the log passed, if there is one.

    smartctl lists the newest entry first, in the extended log when the drive
    has it and in the standard log otherwise.
    """
    for log in ("extended", "standard"):
        tests = entries(document, "ata_smart_self_test_log", log, "table")
        if tests:
            return flag(section(tests[0], "status"), "passed")
    return None


def _error_log_count(document: Mapping[str, object]) -> int | None:
    log = section(document, "ata_smart_error_log")
    count = integer(section(log, "extended"), "count")
    return count if count is not None else integer(section(log, "summary"), "count")
