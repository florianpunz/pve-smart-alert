# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wear value of an SSD and where it comes from (ADR 0021, FR-312).

The first source a drive reports wins: `endurance_used.current_percent` of
smartmontools 7.5 (vendor-neutral only with the device statistics read,
Research 03), then the indicator of the protocol, then the vendor attribute
the web interface of Proxmox VE reads, as `100 - value` (ADR 0021).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from pve_smart_alert.model import WearSource
from pve_smart_alert.parsers.common import entries, flag, integer, section, text

# The list of the web interface, in its order (PVE/Diskmanage.pm). A value
# falls as the drive wears, also under a name with "*_Used": mirror the web
# interface and do not invert it here.
WEB_INTERFACE_ATTRIBUTES: Final = (
    "Media_Wearout_Indicator",
    "SSD_Life_Left",
    "Wear_Leveling_Count",
    "Perc_Write/Erase_Ct_BC",
    "Perc_Rated_Life_Remain",
    "Remaining_Lifetime_Perc",
    "Percent_Lifetime_Remain",
    "Lifetime_Left",
    "PCT_Life_Remaining",
    "Lifetime_Remaining",
    "Percent_Life_Remaining",
    "Percent_Lifetime_Used",
    "Perc_Rated_Life_Used",
)

DEVICE_STATISTICS_ENTRY: Final = "Percentage Used Endurance Indicator"

# The metrics of a snapshot that hold the two values.
WEAR_METRIC: Final = "wear.percent_used"
WEB_INTERFACE_METRIC: Final = "wear.web_interface_percent_used"


@dataclass(frozen=True)
class Wear:
    """The wear value of a drive, its source, and what the web interface shows."""

    percent_used: int | None = None
    source: WearSource | None = None
    web_interface: int | None = None


def ata_wear(document: Mapping[str, object]) -> Wear:
    """Return the wear of an ATA drive."""
    web_interface = vendor_attribute_wear(document)
    statistics = device_statistics_wear(document)
    endurance = _endurance_used(document)
    if endurance is not None and statistics is not None:
        # With the device statistics read, smartmontools overrides its own
        # attribute guess with their standard value (Research 03), so
        # `endurance_used` is the vendor-neutral source of ADR 0021.
        return Wear(endurance, WearSource.ENDURANCE_USED, web_interface)
    if statistics is not None:
        return Wear(statistics, WearSource.DEVICE_STATISTICS, web_interface)
    if web_interface is not None:
        return Wear(web_interface, WearSource.VENDOR_ATTRIBUTE, web_interface)
    if endurance is not None:
        # Without the device statistics, smartmontools guesses `endurance_used`
        # from a vendor attribute, so it counts as a vendor attribute, not as
        # the vendor-neutral first source.
        return Wear(endurance, WearSource.VENDOR_ATTRIBUTE, web_interface)
    return Wear()


def nvme_wear(document: Mapping[str, object]) -> Wear:
    """Return the wear of an NVMe drive."""
    health_log = integer(section(document, "nvme_smart_health_information_log"), "percentage_used")
    endurance = _endurance_used(document)
    if endurance is not None:
        return Wear(endurance, WearSource.ENDURANCE_USED, health_log)
    if health_log is not None:
        return Wear(health_log, WearSource.HEALTH_LOG, health_log)
    return Wear()


def scsi_wear(document: Mapping[str, object]) -> Wear:
    """Return the wear of a SCSI drive.

    smartmontools 7.5 writes the indicator under both keys, 7.3 and 7.4 only
    as `scsi_percentage_used_endurance_indicator` (Research 08). The web
    interface shows no wear for SAS drives.
    """
    endurance = _endurance_used(document)
    if endurance is not None:
        return Wear(endurance, WearSource.ENDURANCE_USED)
    indicator = integer(document, "scsi_percentage_used_endurance_indicator")
    if indicator is not None:
        return Wear(indicator, WearSource.ENDURANCE_INDICATOR)
    return Wear()


def vendor_attribute_wear(document: Mapping[str, object]) -> int | None:
    """Return the wear the web interface shows for an ATA drive, or `None`."""
    attributes = entries(document, "ata_smart_attributes", "table")
    for wanted in WEB_INTERFACE_ATTRIBUTES:
        for attribute in attributes:
            name = text(attribute, "name")
            if name is None or wanted not in name:
                continue
            value = integer(attribute, "value")
            if value is not None:
                # The same 100 - value for every name, as the web interface does.
                return 100 - value
            # Like the web interface: the next name of the list is tried.
            break
    return None


def device_statistics_wear(document: Mapping[str, object]) -> int | None:
    """Return the Percentage Used Endurance Indicator of the device statistics, or `None`."""
    for page in entries(document, "ata_device_statistics", "pages"):
        for entry in entries(page, "table"):
            if text(entry, "name") == DEVICE_STATISTICS_ENTRY:
                if flag(section(entry, "flags"), "valid") is False:
                    return None
                return integer(entry, "value")
    return None


def _endurance_used(document: Mapping[str, object]) -> int | None:
    return integer(section(document, "endurance_used"), "current_percent")
