# SPDX-License-Identifier: AGPL-3.0-or-later
"""The models of the tool: notifications and drives.

One notification is one message that the tool hands to a transport. This
module holds its shape, the severity vocabulary of the tool, and the mapping
onto the severities of the Proxmox VE notification system (ADR 0008).

One snapshot is what one run learned about one drive (ARCHITECTURE.md
section 4). The parsers translate the output of smartctl into snapshots, and
the checks read nothing else: they never see smartctl JSON (ADR 0004).
"""

from __future__ import annotations

import re
import socket
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

# The value of the `type` field of every notification (FR-502). It is also the
# name of the two template files and of the template the bridge asks for, so
# that a matcher, a webhook body and the templates use the same word
# (ADR 0008).
NOTIFICATION_TYPE: Final = "pve-smart-alert"

FIELD_TYPE: Final = "type"
FIELD_HOSTNAME: Final = "hostname"
FIELD_EVENT: Final = "event"
# A notification about a single drive carries these as well (FR-503).
FIELD_DEVICE: Final = "device"
FIELD_SERIAL: Final = "serial"
FIELD_MODEL: Final = "model"
# Only a drive read through a pass-through type carries this one: the device
# ID of the drive behind the controller, which `device` does not tell apart
# (FR-503, ADR 0029). Every other notification leaves it out.
FIELD_DEVICE_ID: Final = "device-id"

# The pass-through types that address one drive behind a controller, with
# its device ID: `megaraid,N` for a SAS or SCSI drive and `sat+megaraid,N`
# for a SATA drive behind a MegaRAID controller (ADR 0028), and `cciss,N`
# behind an HPE Smart Array controller (ADR 0032). `scsi+` before either names
# the SCSI pass-through itself, which is the documented way to switch the
# implicit SAT of a cciss device off. The first group is the base type and the
# second the device ID.
_PASS_THROUGH_TYPE: Final = re.compile(r"(?:sat\+|scsi\+)?(megaraid|cciss),([0-9]+)")

# The types that read a drive behind a controller through a node of the host
# that is not the drive: the two above, and the other controller types of
# smartctl(8) of 7.4 and 7.5 (Research 04, ADR 0034): `3ware,N`, `areca,N`
# and `areca,N/E`, `aacraid,H,L,ID`, `hpt,L/M` and `hpt,L/M/N`, and
# `sssraid,E,S`. Before any of them smartctl takes `scsi+` and `sat` with its
# options, such as `sat,auto+` (dev_interface.cpp of 7.5). The node can be a
# logical volume, such as /dev/sda for `aacraid` and `hpt`, so what the host
# tells about it is not about the drive.
BEHIND_CONTROLLER_TYPE: Final = re.compile(
    r"(?:sat(?:,[a-z0-9]+)*\+|scsi\+)?"
    r"(?:megaraid|cciss|3ware|areca|aacraid|hpt|sssraid),[0-9][0-9,/]*"
)

# Longer field values are cut. Field values go into the configuration of the
# notification system and drive data is untrusted (ARCHITECTURE.md section 14).
MAX_FIELD_VALUE: Final = 128


class Severity(StrEnum):
    """Severity of the tool, seen from the finding.

    `INFO` is not a finding severity: it carries recoveries, first-run
    summaries without findings and test notifications (ADR 0008, FR-513).
    """

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


class PveSeverity(StrEnum):
    """The severities the Proxmox VE notification system accepts."""

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"


#: How the severities of the tool are named towards Proxmox VE (ADR 0008).
PVE_SEVERITY: Final[Mapping[Severity, PveSeverity]] = {
    Severity.INFO: PveSeverity.INFO,
    Severity.NOTICE: PveSeverity.NOTICE,
    Severity.WARNING: PveSeverity.WARNING,
    Severity.CRITICAL: PveSeverity.ERROR,
}

#: The way back: a severity named by Proxmox VE, as the `test-notification`
#: command takes it, belongs to exactly one severity of the tool (FR-520).
SEVERITY_FOR_PVE: Final[Mapping[PveSeverity, Severity]] = {
    pve: severity for severity, pve in PVE_SEVERITY.items()
}


class EventType(StrEnum):
    """Why a notification is sent (ARCHITECTURE.md section 4)."""

    PROBLEM = "problem"
    ESCALATED = "escalated"
    WORSENED = "worsened"
    REMINDER = "reminder"
    RECOVERED = "recovered"
    MISSING = "missing"
    SUMMARY = "summary"
    FIRST_RUN = "first-run"
    TOOL = "tool"
    TEST = "test"


# Longer strings of a drive are cut where `scan`, `status` and `check
# --dry-run` print them, as in a message (ARCHITECTURE.md section 14).
MAX_PRINTED: Final = 200


def without_controls(text: str) -> str:
    """Return `text` with every control character replaced by a space.

    These are the characters of the Unicode category Cc: the C0 controls,
    among them escape, carriage return and newline, DEL, and the C1 controls
    from U+0080 to U+009F, among them the 8-bit introducer of an ANSI escape
    sequence (U+009B) and NEL (U+0085). A string from a drive that keeps
    none of them cannot move the cursor, colour a terminal or start a line
    of its own (ARCHITECTURE.md section 14).
    """
    return "".join(
        " " if unicodedata.category(character) == "Cc" else character for character in text
    )


def printable(value: str, *, limit: int) -> str:
    """Return a string from a drive, safe to print or to write into a message.

    Control characters are replaced by spaces, runs of whitespace are
    collapsed, and the result is cut to `limit` characters (ARCHITECTURE.md
    section 14).
    """
    return " ".join(without_controls(value).split())[:limit]


def sanitize_field_value(value: str, *, limit: int = MAX_FIELD_VALUE) -> str:
    """Return a metadata value that is safe for the notification system.

    A field value never contains a comma, because Proxmox VE splits the value
    list of an exact matcher on commas, so a comma inside a value would change
    the meaning of a rule. Otherwise it is `printable`, so that a value cannot
    break the line it is written to (ADR 0008, ARCHITECTURE.md section 14).
    """
    return printable(value.replace(",", ";"), limit=limit)


@dataclass(frozen=True)
class Notification:
    """One message that is ready to be handed to a transport.

    `node` is the name of the host the message is about, `subject` and `body`
    are the rendered plain text; both transports send the same text. `fields`
    are the metadata values of the single drive or event the notification is
    about (FR-503); `type` and `hostname` are added by `fields_for`. `data` is
    the structured payload the templates of the notification system can use in
    addition to the two texts.
    """

    event: EventType
    severity: Severity
    node: str
    subject: str
    body: str
    fields: Mapping[str, str] = field(default_factory=dict)
    data: Mapping[str, object] = field(default_factory=dict)

    def fields_for(self) -> dict[str, str]:
        """Return the complete metadata fields of this notification.

        Every notification carries `type` and `hostname` (FR-502); the other
        fields describe a single drive (FR-503). The two fixed fields are set
        last, so that a caller cannot replace them by accident: matchers and
        webhook bodies rely on them.
        """
        merged = dict(self.fields)
        merged[FIELD_TYPE] = NOTIFICATION_TYPE
        merged[FIELD_HOSTNAME] = self.node
        return {name: sanitize_field_value(value) for name, value in merged.items()}


def pass_through_id(device_type: str) -> str | None:
    """Return the device ID of a type that addresses a drive behind a controller.

    `megaraid,N` reaches a SAS or SCSI drive, `sat+megaraid,N` a SATA drive,
    both behind a MegaRAID controller; `cciss,N` reaches a drive behind an HPE
    Smart Array controller, where `N` is its position in the device list of the
    controller (ADR 0032). `scsi+` before either names the SCSI pass-through,
    which the manual of smartctl recommends for a cciss device whose implicit
    SAT is not wanted (ADR 0032). The ID is `N` as the type writes it. Any
    other type reads the device itself, and the answer is `None`. The location
    that `scan` and a message show and the field `device-id` both come from
    here, so that they cannot disagree (ADR 0028, ADR 0029).
    """
    match = _PASS_THROUGH_TYPE.fullmatch(device_type)
    return match.group(2) if match is not None else None


def behind_controller(device_type: str) -> bool:
    """Whether a type reads a drive behind a controller, not the node it is given.

    The location, the membership and the inquiry data that the host shows
    for the node are then not those of the drive (ADR 0028). Only the types
    of `pass_through_id` have a device ID as well.
    """
    return BEHIND_CONTROLLER_TYPE.fullmatch(device_type) is not None


def is_cciss_type(device_type: str) -> bool:
    """Whether a type names a drive behind an HPE Smart Array controller (ADR 0032).

    Such a drive is found only by the probe or named by a manual entry of the
    same form. When the configuration switches the probe off, its drives are
    forgotten silently instead of being reported as missing (ADR 0032).
    """
    match = _PASS_THROUGH_TYPE.fullmatch(device_type)
    return match is not None and match.group(1) == "cciss"


def node_name(hostname: str | None = None) -> str:
    """Return the name of this node, which is its short host name.

    Proxmox VE uses the short host name as the node name, so a fully qualified
    host name is cut at the first dot.
    """
    value = socket.gethostname() if hostname is None else hostname
    return value.split(".", 1)[0]


class DriveClass(StrEnum):
    """The class of a drive, which decides the checks and limits that apply.

    SATA and SAS drives are `hdd` or `ssd` by their rotation rate, and an
    unknown rate counts as `hdd` (docs/check-catalog.md).
    """

    HDD = "hdd"
    SSD = "ssd"
    NVME = "nvme"


class WearSource(StrEnum):
    """Where the wear value of a drive comes from, in the order of ADR 0021.

    `pve-smart-alert scan` shows it next to the value, for example
    "44 % (device statistics)".
    """

    # The value smartmontools 7.5 and later computes itself.
    ENDURANCE_USED = "endurance_used"
    # ATA: the Percentage Used Endurance Indicator of the device statistics.
    DEVICE_STATISTICS = "device statistics"
    # NVMe: `percentage_used` of the SMART health log.
    HEALTH_LOG = "health log"
    # SAS: the percentage used endurance indicator.
    ENDURANCE_INDICATOR = "endurance indicator"
    # ATA only: the attribute the web interface of Proxmox VE reads.
    VENDOR_ATTRIBUTE = "vendor attribute"


def normalize(value: str) -> str:
    """Return a value a drive reports, trimmed and with inner whitespace collapsed.

    Drives pad their model names and serial numbers, and the padding differs
    between protocols and bridges (ADR 0005).
    """
    return " ".join(value.split())


@dataclass(frozen=True)
class DriveIdentity:
    """Who a drive is: model and serial number, and the WWN where known.

    Device node, smartctl type and controller ID are attributes of a drive and
    never part of its identity (ADR 0005, FR-105). Two identities are the same
    drive when they are equal.
    """

    model: str
    serial: str | None = None
    wwn: str | None = None

    @classmethod
    def of(
        cls, model: str | None, *, serial: str | None = None, wwn: str | None = None
    ) -> DriveIdentity:
        """Return the identity from the values a drive reports.

        Values are normalized, an empty value counts as missing, and a WWN is
        written as lowercase hexadecimal digits without a prefix.
        """
        return cls(
            model=normalize(model or ""),
            serial=_present(serial),
            wwn=_normal_wwn(wwn),
        )

    @property
    def stable(self) -> bool:
        """Whether the identity survives a change of path.

        It needs a serial number or a WWN. A drive without either is monitored,
        but it is exempt from the detection of missing drives (ADR 0005,
        FR-309).
        """
        return self.serial is not None or self.wwn is not None


@dataclass(frozen=True)
class DeviceAccess:
    """How a drive is reached: the arguments smartctl gets (ADR 0004).

    `aliases` are the other paths to the same drive that discovery set aside
    (ADR 0005).
    """

    name: str
    type: str
    protocol: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Location:
    """Where a drive sits, as far as the host tells. Shown, never part of the identity."""

    transport: str | None = None
    removable: bool | None = None
    by_id: tuple[str, ...] = ()
    by_path: str | None = None
    # A drive behind a RAID controller: the controller, such as
    # "/dev/bus/6 (megaraid_sas)", and the device ID of the drive on it.
    controller: str | None = None
    device_id: str | None = None

    @property
    def controller_text(self) -> str | None:
        """Return controller and device ID as `scan` and notifications show them (FR-507)."""
        if self.controller is None or self.device_id is None:
            return None
        return f"{self.controller}, device {self.device_id}"


@dataclass(frozen=True)
class Membership:
    """What uses a drive, if that is known (FR-110)."""

    zfs_pool: str | None = None
    md_array: str | None = None
    volume_group: str | None = None


@dataclass(frozen=True)
class FailingAttribute:
    """An ATA attribute whose normalized value is at or below its threshold now."""

    id: int
    name: str
    prefailure: bool


@dataclass(frozen=True)
class Collection:
    """How the data of a snapshot was obtained in this run (ADR 0004)."""

    smartctl_version: tuple[int, ...]
    exit_status: int
    messages: tuple[str, ...] = ()
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class Snapshot:
    """What one run learned about one drive (ARCHITECTURE.md section 4).

    `metrics` maps a metric name to its value, for example `ata.attr.5.raw`,
    `nvme.available_spare`, `temperature.current` or `wear.percent_used`. A
    missing metric or flag is not applicable, and a check never guesses it
    (FR-206). `wear_source` says where `wear.percent_used` comes from
    (ADR 0021).
    """

    identity: DriveIdentity
    access: DeviceAccess
    drive_class: DriveClass
    collection: Collection
    firmware: str | None = None
    capacity_bytes: int | None = None
    location: Location = field(default_factory=Location)
    membership: Membership = field(default_factory=Membership)
    smart_available: bool | None = None
    smart_enabled: bool | None = None
    health_passed: bool | None = None
    # What the drive says about a failed health verdict, where it says more
    # than "failed": for SCSI the informational exception and its codes.
    health_detail: str | None = None
    nvme_critical_warning: int | None = None
    failing_attributes: tuple[FailingAttribute, ...] = ()
    last_self_test_passed: bool | None = None
    power_on_hours: int | None = None
    power_cycles: int | None = None
    metrics: Mapping[str, int] = field(default_factory=dict)
    wear_source: WearSource | None = None


class CheckKind(StrEnum):
    """Whether a check watches a state or an increase (docs/check-catalog.md).

    A *condition* is active until it clears, with reminders and recovery. An
    *event* is an increase of a cumulative counter above the stored baseline;
    without a baseline there is nothing to report (FR-306).
    """

    CONDITION = "condition"
    EVENT = "event"


@dataclass(frozen=True)
class Finding:
    """What one check found about one drive (ARCHITECTURE.md section 4).

    `value` is the current value of the source and `threshold` the one that
    was crossed; both are `None` for a plain flag. `text` names the finding
    with its value and threshold, for the report of a dry run and for a
    notification. `check` is the stable identifier of the check, which the
    configuration and the notifications name as well (ADR 0010).
    """

    check: str
    kind: CheckKind
    severity: Severity
    text: str
    value: int | None = None
    threshold: int | None = None


def _present(value: str | None) -> str | None:
    """Return a value normalized, or `None` when it is missing or empty."""
    if value is None:
        return None
    return normalize(value) or None


def _normal_wwn(value: str | None) -> str | None:
    """Return a WWN as lowercase hexadecimal digits without a prefix, or `None`."""
    if value is None:
        return None
    digits = value.strip().lower().removeprefix("0x")
    return digits or None
