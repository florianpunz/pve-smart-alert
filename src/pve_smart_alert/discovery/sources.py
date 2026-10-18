# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where discovery finds devices: the device scan of smartctl and the manual entries.

The scan is `smartctl --scan-open --json=c`. For every device it writes the
name, the type and the protocol, and for a device it could not open also
`open_error`, in 7.4 and 7.5 alike (Research 03). Name and type are always
kept together (ADR 0005). The probes for controllers the scan cannot see
build their devices in `probes.py` (ADR 0032).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from pve_smart_alert.collect import JSON_FORMAT_MAJOR, version_of
from pve_smart_alert.config import (
    DEVICE_NAME_PATTERN,
    DEVICE_TYPE_PATTERN,
    WRITING_DEVICE_TYPE,
    ManualDevice,
    SmartctlSettings,
)
from pve_smart_alert.process import ProcessRunner, run_with_timeout


class Source(StrEnum):
    """What found a device (FR-108)."""

    SCAN = "scan"
    # The probe for the drives behind an HPE Smart Array controller (FR-103,
    # ADR 0032).
    PROBE = "probe"
    MANUAL = "manual"


@dataclass(frozen=True)
class Candidate:
    """A device that discovery found, before it is read."""

    name: str
    type: str
    source: Source
    protocol: str | None = None
    open_error: str | None = None

    @property
    def valid(self) -> bool:
        """Whether name and type have the form that may reach smartctl.

        Both are passed as arguments, so they are checked against strict
        patterns, also when the scan reports them (ARCHITECTURE.md section 14).
        A type that smartctl reads by writing to the drive never reaches it,
        from whichever source it comes (ADR 0012, ADR 0034).
        """
        return (
            DEVICE_NAME_PATTERN.fullmatch(self.name) is not None
            and ".." not in PurePosixPath(self.name).parts
            and DEVICE_TYPE_PATTERN.fullmatch(self.type) is not None
            and WRITING_DEVICE_TYPE.search(self.type) is None
        )


@dataclass(frozen=True)
class Scan:
    """What the device scan returned: the devices, or why there are none."""

    candidates: tuple[Candidate, ...] = ()
    smartctl_version: tuple[int, ...] = ()
    error: str | None = None


def scan_command(settings: SmartctlSettings) -> list[str]:
    return [str(settings.path), "--scan-open", "--json=c"]


def run_scan(settings: SmartctlSettings, *, runner: ProcessRunner = run_with_timeout) -> Scan:
    """Run the device scan of smartctl and return its devices."""
    try:
        result = runner(scan_command(settings), timeout=settings.timeout_seconds)
    except OSError as failure:
        return Scan(error=f"smartctl could not be started: {failure.strerror or failure}")
    if result.timed_out:
        return Scan(
            error=f"the device scan did not answer within {settings.timeout_seconds:g} seconds"
        )
    return parse_scan(result.stdout)


def parse_scan(stdout: str) -> Scan:
    """Return the devices of the JSON the device scan answered with."""
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError:
        return Scan(error="the device scan answered without valid JSON")
    if not isinstance(document, dict):
        return Scan(error="the device scan answered without valid JSON")

    version = document.get("json_format_version")
    if not (isinstance(version, list) and version and version[0] == JSON_FORMAT_MAJOR):
        return Scan(error="the device scan writes another JSON format")
    devices = document.get("devices", [])
    if not isinstance(devices, list):
        return Scan(error="the device scan answered without a list of devices")

    candidates = [_candidate(entry) for entry in devices if isinstance(entry, dict)]
    return Scan(
        candidates=tuple(candidate for candidate in candidates if candidate is not None),
        smartctl_version=version_of(document),
    )


def manual_candidates(devices: Sequence[ManualDevice]) -> tuple[Candidate, ...]:
    """Return the manual entries of the configuration, in their order (FR-104)."""
    return tuple(Candidate(device.name, device.type, Source.MANUAL) for device in devices)


def _candidate(entry: Mapping[str, object]) -> Candidate | None:
    name, device_type = entry.get("name"), entry.get("type")
    if not isinstance(name, str) or not isinstance(device_type, str):
        return None
    protocol, open_error = entry.get("protocol"), entry.get("open_error")
    return Candidate(
        name=name,
        type=device_type,
        source=Source.SCAN,
        protocol=protocol if isinstance(protocol, str) else None,
        open_error=open_error if isinstance(open_error, str) else None,
    )
