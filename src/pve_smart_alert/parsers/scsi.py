# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parser for SCSI drives: SAS and parallel SCSI hard disks and SSDs (ADR 0004).

The keys are those of smartmontools 7.3 and later (`scsi_model_name`,
`scsi_revision`), with the names of 7.0 to 7.2 (`model_name`, `revision`) as
the fallback (Research 08). The values of the log pages become metrics
named `scsi.*`:

- `scsi.grown_defects`: the elements of the grown defect list;
- `scsi.uncorrected_errors`: the uncorrected errors of the error counter
  log, read, write and verify added up, of the parts the drive reports;
- `scsi.pending_defects`: the pending defects, which smartctl reads only
  with `--xall` and only from drives that have the log page.

The health verdict of a SCSI drive is missing when the drive has no
informational exceptions mode page, and then it is not applicable: only an
explicit `false` is a failed verdict (Research 08). The non-medium error
count is not read; smartctl writes it only as text (docs/check-catalog.md).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from pve_smart_alert.model import Collection, DeviceAccess, DriveIdentity, Snapshot
from pve_smart_alert.parsers.ata import drive_class_of
from pve_smart_alert.parsers.common import (
    ParseError,
    capacity_of,
    flag,
    integer,
    put,
    section,
    text,
)
from pve_smart_alert.parsers.wear import WEAR_METRIC, scsi_wear

# The parts of the error counter log (`scsiprint.cpp`, Research 08).
ERROR_COUNTER_PARTS: Final = ("read", "write", "verify")

# The result codes of a self-test in the SCSI self-test log: 0 completed
# without error, 3 to 7 an error or a failed segment, for which smartctl sets
# its own failure bits. 1 and 2 are aborted tests and 15 a test in progress,
# neither a failure (`scsiprint.cpp`, SPC-3 section 7.2.10).
_SELF_TEST_PASSED: Final = 0
_SELF_TEST_FAILED: Final = frozenset({3, 4, 5, 6, 7})

# A logical unit id that is a WWN: NAA 5, 16 hexadecimal digits (ADR 0026,
# ARCHITECTURE.md section 4).
_WWN_NAME: Final = re.compile(r"0x(5[0-9a-f]{15})", re.IGNORECASE)


@dataclass(frozen=True)
class Inquiry:
    """What a SCSI device says about itself in its inquiry data.

    Discovery reads it before the output becomes a snapshot, to skip a
    logical volume or a device that is not a disk (ADR 0028).
    """

    vendor: str | None = None
    product: str | None = None
    # The peripheral device type: 0 a disk, 13 an enclosure, and so on.
    peripheral_type: int | None = None
    peripheral_name: str | None = None


def inquiry_of(document: Mapping[str, object]) -> Inquiry:
    """Return the inquiry data of a SCSI drive output.

    The keys are `scsi_vendor` and `scsi_product` from smartmontools 7.3 on,
    and `vendor` and `product` in 7.0 to 7.2 (Research 08).
    """
    device_type = section(document, "device_type")
    return Inquiry(
        vendor=_first_text(document, "scsi_vendor", "vendor"),
        product=_first_text(document, "scsi_product", "product"),
        peripheral_type=integer(device_type, "scsi_value"),
        peripheral_name=text(device_type, "name"),
    )


def parse(
    document: Mapping[str, object], *, access: DeviceAccess, collection: Collection
) -> Snapshot:
    """Return the snapshot of the output of smartctl for one SCSI drive."""
    support = section(document, "smart_support")
    status = section(document, "smart_status")
    wear = scsi_wear(document)
    metrics: dict[str, int] = {}
    put(metrics, WEAR_METRIC, wear.percent_used)
    # The temperature is in °C on every protocol.
    put(metrics, "temperature.current", integer(section(document, "temperature"), "current"))
    put(metrics, "scsi.grown_defects", integer(document, "scsi_grown_defect_list"))
    put(metrics, "scsi.uncorrected_errors", _uncorrected_errors(document))
    pending = integer(section(document, "scsi_pending_defects"), "count")
    put(metrics, "scsi.pending_defects", pending)

    return Snapshot(
        identity=identity_of(document),
        access=access,
        drive_class=drive_class_of(document),
        collection=collection,
        firmware=_first_text(document, "scsi_revision", "revision"),
        capacity_bytes=capacity_of(document),
        smart_available=flag(support, "available"),
        smart_enabled=flag(support, "enabled"),
        health_passed=flag(status, "passed"),
        health_detail=_health_detail(status),
        last_self_test_passed=_last_self_test(document),
        power_on_hours=integer(section(document, "power_on_time"), "hours"),
        power_cycles=integer(
            section(document, "scsi_start_stop_cycle_counter"), "accumulated_start_stop_cycles"
        ),
        metrics=metrics,
        wear_source=wear.source,
    )


def identity_of(document: Mapping[str, object]) -> DriveIdentity:
    """Return the identity of a SCSI drive: model, serial number and its WWN.

    The WWN is the logical unit id where that is an NAA 5 name, which is the
    WWN that lsblk shows for the same drive (ARCHITECTURE.md section 4).
    Raises `ParseError` without a model name.
    """
    model = _first_text(document, "scsi_model_name", "model_name")
    if not model or not model.strip():
        raise ParseError("smartctl reported no model name")
    name = _WWN_NAME.fullmatch(text(document, "logical_unit_id") or "")
    return DriveIdentity.of(
        model,
        serial=text(document, "serial_number"),
        wwn=name.group(1) if name is not None else None,
    )


def _uncorrected_errors(document: Mapping[str, object]) -> int | None:
    """Return the uncorrected errors of the parts the drive reports, or `None`."""
    log = section(document, "scsi_error_counter_log")
    values = [
        value
        for part in ERROR_COUNTER_PARTS
        if (value := integer(section(log, part), "total_uncorrected_errors")) is not None
    ]
    return sum(values) if values else None


def _health_detail(status: Mapping[str, object]) -> str | None:
    """Return what a drive says about a failed verdict: the exception and its codes."""
    exception = section(status, "scsi")
    asc, ascq = integer(exception, "asc"), integer(exception, "ascq")
    words = (text(exception, "ie_string") or "").strip()
    codes = f"ASC 0x{asc:02x}, ASCQ 0x{ascq:02x}" if asc is not None and ascq is not None else ""
    detail = f"{words} ({codes})" if words and codes else words or codes
    return detail or None


def _last_self_test(document: Mapping[str, object]) -> bool | None:
    """Return whether the most recent self-test passed, if the log says.

    The log lists the most recent test first, as `scsi_self_test_0`. An
    aborted test, or one in progress, says nothing either way.
    """
    result = integer(section(document, "scsi_self_test_0", "result"), "value")
    if result == _SELF_TEST_PASSED:
        return True
    if result in _SELF_TEST_FAILED:
        return False
    return None


def _first_text(document: Mapping[str, object], *keys: str) -> str | None:
    """Return the first of several keys that holds a text."""
    for key in keys:
        value = text(document, key)
        if value is not None:
            return value
    return None
