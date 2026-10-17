# SPDX-License-Identifier: AGPL-3.0-or-later
"""Running smartctl for one drive (ADR 0004).

One call per drive, with the name and the type that discovery found, as an
argument list, with a timeout that ends the call and everything it started.
Only options that read are ever passed: no option enables SMART, changes a
setting or starts a test (ADR 0012).

The answer is judged the way ADR 0004 lays down. Bits 0 and 1 of the exit
status mean that no usable data came back; bit 2 alone is tolerated, and the
higher bits are hints that the checks read from the JSON instead. A drive in
standby is not read and is skipped for this run (FR-203). Everything else
that keeps the data from being usable makes the drive unreadable for this
run, which never stops the run (FR-205).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pve_smart_alert.config import Detail, SmartctlSettings
from pve_smart_alert.process import ProcessRunner, run_with_timeout

# Bit 0: the command line was not accepted. Bit 1: the device could not be
# opened, or it is in a low-power mode (smartctl.h, FAILDEV and FAILPOWER).
NO_DATA_BITS: Final = 0b11
FAILPOWER: Final = 0b10

# What smartctl writes when `--nocheck=standby` ends the call before the data,
# in 7.4 and 7.5: an information message that names the power mode and the
# exit status of FAILPOWER, for ATA (ataprint.cpp) and for SCSI
# (scsiprint.cpp) alike. 7.5 adds `power_mode` to the JSON for ATA.
STANDBY_MESSAGE: Final = re.compile(r"Device is in (\S+) mode")

# The major version of the JSON format this tool reads (ADR 0004).
JSON_FORMAT_MAJOR: Final = 1

# The device types for which the tool passes `--nocheck=standby` (FR-203,
# ADR 0004): `ata`, the SCSI to ATA translation `sat` with its variants such as
# `sat+megaraid,N`, and the USB bridges.
_STANDBY_TYPES: Final = re.compile(r"(?:ata|sat|usb[a-z0-9]*|jm[bs][0-9a-z-]*)(?:[,+].*)?")

# The types of a drive behind an HPE Smart Array, 3ware, Areca, Adaptec,
# HighPoint or SSSRAID controller, which get the standby check whatever their
# protocol says: such a drive can be a SATA drive, behind 3ware, Areca and
# HighPoint it always is, and smartctl implements the power mode check for SCSI
# as well (ADR 0032, ADR 0034). MegaRAID is not among them, because its type
# tells a SATA drive (`sat+megaraid,N`) from a SAS drive (`megaraid,N`).
_CONTROLLER_TYPES: Final = re.compile(
    r"(?:sat(?:,[a-z0-9]+)*\+|scsi\+)?(?:cciss|3ware|areca|aacraid|hpt|sssraid),[0-9][0-9,/]*"
)


class Status(StrEnum):
    """How the call for one drive ended."""

    OK = "ok"
    # The drive sleeps and was not woken; it keeps its previous state.
    STANDBY = "standby"
    # No usable data in this run.
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class Collected:
    """What one call of smartctl for one drive left behind.

    `document` is the JSON when the data is usable. `reason` says why a drive
    is unreadable, or names the power mode of a drive in standby.
    """

    status: Status
    command: tuple[str, ...]
    duration_seconds: float
    exit_status: int | None = None
    messages: tuple[str, ...] = ()
    document: Mapping[str, object] | None = None
    reason: str | None = None

    @property
    def smartctl_version(self) -> tuple[int, ...]:
        """The version of smartctl that answered, or `()` when it is not known."""
        return version_of(self.document)


def checks_standby(device_type: str, protocol: str | None = None) -> bool:
    """Whether smartctl is asked not to wake a drive in standby (FR-203).

    The option is `--nocheck=standby`, and a call that ends because of it is
    recorded as standby, not as unreadable (ADR 0004). A drive behind an HPE
    Smart Array, 3ware, Areca, Adaptec, HighPoint or SSSRAID controller is
    included whatever its protocol says, because it can be a SATA drive and
    smartctl checks the power mode for SCSI as well (ADR 0032, ADR 0034). For
    every other type the protocol of the device scan decides where it is
    known, and for a manual device the type does.
    """
    if _CONTROLLER_TYPES.fullmatch(device_type) is not None:
        return True
    if protocol is not None:
        return protocol == "ATA"
    return _STANDBY_TYPES.fullmatch(device_type) is not None


def drive_command(
    name: str,
    device_type: str,
    *,
    settings: SmartctlSettings,
    protocol: str | None = None,
) -> list[str]:
    """Return the command line for one drive (ADR 0004)."""
    detail = "--xall" if settings.detail is Detail.EXTENDED else "--all"
    command = [str(settings.path), "--json=c", detail, f"--device={device_type}"]
    if checks_standby(device_type, protocol):
        command.append("--nocheck=standby")
    command.append(name)
    return command


def collect_drive(
    name: str,
    device_type: str,
    *,
    settings: SmartctlSettings,
    protocol: str | None = None,
    runner: ProcessRunner = run_with_timeout,
    clock: Callable[[], float] = time.monotonic,
) -> Collected:
    """Run smartctl for one drive and judge its answer."""
    command = drive_command(name, device_type, settings=settings, protocol=protocol)
    started = clock()
    try:
        result = runner(command, timeout=settings.timeout_seconds)
    except OSError as failure:
        return Collected(
            Status.UNREADABLE,
            tuple(command),
            clock() - started,
            reason=f"smartctl could not be started: {failure.strerror or failure}",
        )
    duration = clock() - started

    if result.timed_out:
        return Collected(
            Status.UNREADABLE,
            tuple(command),
            duration,
            reason=f"smartctl did not answer within {settings.timeout_seconds:g} seconds",
        )
    return judge(result.stdout, result.returncode, command=command, duration=duration)


def judge(
    stdout: str,
    exit_status: int | None,
    *,
    command: Sequence[str],
    duration: float,
) -> Collected:
    """Return what an answer of smartctl for one drive means (ADR 0004)."""
    document = _document(stdout)
    if document is None:
        return Collected(
            Status.UNREADABLE,
            tuple(command),
            duration,
            exit_status=exit_status,
            reason="smartctl answered without valid JSON",
        )

    messages = messages_of(document)
    collected = Collected(
        Status.OK,
        tuple(command),
        duration,
        exit_status=exit_status,
        messages=messages,
        document=document,
    )
    major = _format_major(document)
    if major != JSON_FORMAT_MAJOR:
        return _unreadable(collected, f"smartctl writes JSON format {major}, not 1")

    status = exit_status if exit_status is not None else 0
    if status & FAILPOWER:
        for message in messages:
            standby = STANDBY_MESSAGE.search(message)
            if standby is not None:
                return Collected(
                    Status.STANDBY,
                    tuple(command),
                    duration,
                    exit_status=exit_status,
                    messages=messages,
                    reason=standby.group(1),
                )
    if status & NO_DATA_BITS:
        detail = messages[0] if messages else f"smartctl ended with exit status {status}"
        return _unreadable(collected, detail)
    return collected


def messages_of(document: Mapping[str, object]) -> tuple[str, ...]:
    """Return the messages smartctl wrote into its JSON, without line ends."""
    smartctl = document.get("smartctl")
    entries = smartctl.get("messages") if isinstance(smartctl, dict) else None
    if not isinstance(entries, list):
        return ()
    texts = (entry.get("string") for entry in entries if isinstance(entry, dict))
    return tuple(text.strip() for text in texts if isinstance(text, str) and text.strip())


def version_of(document: Mapping[str, object] | None) -> tuple[int, ...]:
    """Return the version of smartctl from its JSON, or `()` when it is not there."""
    smartctl = document.get("smartctl") if document is not None else None
    version = smartctl.get("version") if isinstance(smartctl, dict) else None
    if isinstance(version, list) and all(isinstance(part, int) for part in version):
        return tuple(version)
    return ()


def _unreadable(collected: Collected, reason: str) -> Collected:
    return Collected(
        Status.UNREADABLE,
        collected.command,
        collected.duration_seconds,
        exit_status=collected.exit_status,
        messages=collected.messages,
        reason=reason,
    )


def _document(stdout: str) -> dict[str, object] | None:
    """Return the JSON object smartctl answered with, or `None`."""
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return document if isinstance(document, dict) else None


def _format_major(document: Mapping[str, object]) -> object:
    version = document.get("json_format_version")
    return version[0] if isinstance(version, list) and version else version
