# SPDX-License-Identifier: AGPL-3.0-or-later
"""SCSI hosts whose drives smartctl cannot read (FR-109, ADR 0030).

The SCSI hosts of the host are the directories `hostN` below
`/sys/class/scsi_host`, and the driver of each is its `proc_name`, read by
`scsi_host_driver` of enrichment. A driver is reported only when it is on
the list of drivers whose drives cannot be queried, with the reason and the
source of each entry. Every other driver is not reported: the HBAs whose
drives smartctl reads directly, the enclosure management pseudo-host of
AHCI, the controllers whose drives a probe or a manual entry can reach, and
every driver the tool does not know. Unknown is not unsupported.

Reading sysfs is best effort: a directory that is missing means no SCSI
host, one that cannot be read is reported as such and is no error of a run.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pve_smart_alert.discovery.enrichment import HOST, HostPaths, scsi_host_driver


class Support(StrEnum):
    """What the driver of a SCSI host means for its drives."""

    # smartctl cannot read the drives behind it: reported (ADR 0030).
    UNSUPPORTED = "unsupported"
    # An HBA: smartctl reads its drives directly, as plain SATA or SAS drives.
    DIRECT = "direct"
    # No drive controller at all.
    NOT_A_CONTROLLER = "not-a-controller"
    # Any other driver, known or not: not reported.
    NOT_REPORTED = "not-reported"


@dataclass(frozen=True)
class Limitation:
    """Why the drives behind a driver cannot be queried, and where that is documented."""

    hardware: str
    reason: str
    # The short citation a message names.
    source: str
    url: str


#: The drivers whose drives smartctl cannot read. The list grows with
#: evidence; an entry needs a source that says the drives cannot be queried,
#: not only that the tool does not probe them (ADR 0030).
UNSUPPORTED_DRIVERS: Final[Mapping[str, Limitation]] = {
    "mpi3mr": Limitation(
        hardware="Broadcom MegaRAID 96xx, Dell PERC 12 such as the H965i",
        reason=(
            "smartctl neither lists nor queries the physical drives behind it,"
            " only the virtual drive"
        ),
        source="smartmontools issue 313",
        url="https://github.com/smartmontools/smartmontools/issues/313",
    ),
}

#: The drivers that are never reported, with the reason (ADR 0030). They are
#: listed so that nobody adds them to the list above by mistake.
NEVER_REPORTED: Final[Mapping[str, tuple[Support, str]]] = {
    "mpt2sas": (
        Support.DIRECT,
        "LSI and Broadcom SAS-2 HBAs, such as the SAS2308 of the maintainer's TrueNAS"
        " host; smartctl reads the drives directly (Research 08)",
    ),
    "mpt3sas": (
        Support.DIRECT,
        "LSI and Broadcom SAS-3 HBAs; smartctl reads the drives directly (Research 04,"
        " any controller in HBA or IT mode)",
    ),
    "ahciem": (
        Support.NOT_A_CONTROLLER,
        "the enclosure management pseudo-host of AHCI in newer kernels, next to the"
        " ahci hosts of the same controller (Research 08)",
    ),
}

# The directory of a SCSI host in sysfs.
_HOST_DIRECTORY: Final = re.compile(r"host([0-9]+)")


@dataclass(frozen=True)
class ScsiHost:
    """One SCSI host of the host and its driver, `None` when sysfs does not name one."""

    number: int
    driver: str | None

    @property
    def name(self) -> str:
        return f"host{self.number}"

    @property
    def support(self) -> Support:
        return classify(self.driver)

    @property
    def limitation(self) -> Limitation | None:
        return UNSUPPORTED_DRIVERS.get(self.driver) if self.driver is not None else None

    def describe(self) -> str:
        """Return what a message says about a host whose drives cannot be read."""
        text = (
            f"SCSI host {self.name} has the driver {self.driver}: smartctl cannot read the"
            " drives behind it, so they are not monitored"
        )
        limitation = self.limitation
        if limitation is not None:
            text += f" (upstream limitation, {limitation.source})"
        return text


@dataclass(frozen=True)
class ScsiHosts:
    """The SCSI hosts of the host, or why sysfs could not be read."""

    hosts: tuple[ScsiHost, ...] = ()
    error: str | None = None

    @property
    def unsupported(self) -> tuple[ScsiHost, ...]:
        return tuple(host for host in self.hosts if host.support is Support.UNSUPPORTED)


def classify(driver: str | None) -> Support:
    """Return what a driver means for the drives behind it (ADR 0030)."""
    if driver is None:
        return Support.NOT_REPORTED
    if driver in UNSUPPORTED_DRIVERS:
        return Support.UNSUPPORTED
    known = NEVER_REPORTED.get(driver)
    return known[0] if known is not None else Support.NOT_REPORTED


def read_scsi_hosts(paths: HostPaths = HOST) -> ScsiHosts:
    """Return the SCSI hosts in sysfs with their drivers, in the order of their numbers."""
    directory = paths.sysfs / "class" / "scsi_host"
    try:
        entries = [entry.name for entry in directory.iterdir()]
    except FileNotFoundError:
        return ScsiHosts()
    except OSError as failure:
        return ScsiHosts(error=f"{directory} cannot be read: {failure.strerror or failure}")
    numbers = sorted(
        int(match.group(1))
        for match in (_HOST_DIRECTORY.fullmatch(entry) for entry in entries)
        if match is not None
    )
    return ScsiHosts(
        hosts=tuple(ScsiHost(number, scsi_host_driver(number, paths)) for number in numbers)
    )


def describe_all(hosts: Sequence[ScsiHost]) -> str:
    """Return the message about several hosts whose drives cannot be read."""
    return "; ".join(host.describe() for host in hosts)
