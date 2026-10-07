# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parser for NVMe drives (ADR 0004).

The values of the SMART health log become metrics named `nvme.*`; the
Critical Warning byte becomes a flag that the checks read bit by bit
(docs/check-catalog.md). The drive's own temperature limits are kept as
`temperature.limit.warning` and `temperature.limit.critical`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from pve_smart_alert.model import Collection, DeviceAccess, DriveClass, Snapshot
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

# The keys of `nvme_smart_health_information_log` and their metric names.
HEALTH_METRICS: Final[Mapping[str, str]] = {
    "critical_warning": "nvme.critical_warning",
    "available_spare": "nvme.available_spare",
    "available_spare_threshold": "nvme.available_spare_threshold",
    "percentage_used": "nvme.percentage_used",
    "media_errors": "nvme.media_errors",
    "num_err_log_entries": "nvme.error_log_entries",
    "warning_temp_time": "nvme.warning_temperature_minutes",
    "critical_comp_time": "nvme.critical_temperature_minutes",
    "unsafe_shutdowns": "nvme.unsafe_shutdowns",
}


def parse(
    document: Mapping[str, object], *, access: DeviceAccess, collection: Collection
) -> Snapshot:
    """Return the snapshot of the output of smartctl for one NVMe drive."""
    health = section(document, "nvme_smart_health_information_log")
    temperature = section(document, "temperature")
    support = section(document, "smart_support")

    metrics: dict[str, int] = {}
    for key, metric in HEALTH_METRICS.items():
        put(metrics, metric, integer(health, key))
    put(
        metrics,
        "temperature.current",
        _first(integer(temperature, "current"), integer(health, "temperature")),
    )
    put(metrics, "temperature.limit.warning", integer(temperature, "op_limit_max"))
    put(metrics, "temperature.limit.critical", integer(temperature, "critical_limit_max"))

    return Snapshot(
        identity=identity_of(document),
        access=access,
        drive_class=DriveClass.NVME,
        collection=collection,
        firmware=text(document, "firmware_version"),
        capacity_bytes=capacity_of(document) or integer(document, "nvme_total_capacity"),
        # SMART is part of every NVMe drive; smartctl 7.5 says so explicitly.
        smart_available=flag(support, "available") if support else True,
        smart_enabled=flag(support, "enabled") if support else True,
        health_passed=flag(section(document, "smart_status"), "passed"),
        nvme_critical_warning=integer(health, "critical_warning"),
        last_self_test_passed=_last_self_test(document),
        power_on_hours=_first(
            integer(health, "power_on_hours"),
            integer(section(document, "power_on_time"), "hours"),
        ),
        power_cycles=_first(
            integer(health, "power_cycles"), integer(document, "power_cycle_count")
        ),
        metrics=metrics,
    )


def _first(value: int | None, fallback: int | None) -> int | None:
    """Return the value of the health log, or the general one when it is missing."""
    return value if value is not None else fallback


def _last_self_test(document: Mapping[str, object]) -> bool | None:
    """Return whether the most recent self-test passed: result 0, newest entry first."""
    tests = entries(document, "nvme_self_test_log", "table")
    if not tests:
        return None
    result = integer(section(tests[0], "self_test_result"), "value")
    return None if result is None else result == 0
