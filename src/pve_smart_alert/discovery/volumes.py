# SPDX-License-Identifier: AGPL-3.0-or-later
"""Devices that look like drives and are none: logical volumes and non-disks (ADR 0028).

A logical volume is a block device that smartctl may read without an error, or
one that the scan cannot open and asks for `-d megaraid,N` (FR-107). Inquiry
data come first, because lsblk shows them before the read; the scan message is
only the second signal, since a version can reword it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class VolumeInquiry:
    """Inquiry data that name a logical volume: a vendor, a product, or both.

    `vendor` is compared whole, `product` as a pattern from the start of the
    product. Both are compared trimmed and without case.
    """

    vendor: str | None = None
    product: re.Pattern[str] | None = None

    def matches(self, vendor: str, product: str) -> bool:
        if self.vendor is not None and vendor.casefold() != self.vendor.casefold():
            return False
        return self.product is None or self.product.match(product) is not None


# The inquiry data of logical volumes (ADR 0028): the first four are what
# smartctl takes for a MegaRAID controller (`os_linux.cpp`, 7.4 and 7.5), and
# the last is the Intel RAID volume of Research 08 (Q-R1).
LOGICAL_VOLUMES: Final = (
    VolumeInquiry(vendor="DELL", product=re.compile("PERC", re.IGNORECASE)),
    VolumeInquiry(product=re.compile("PERC ", re.IGNORECASE)),
    VolumeInquiry(vendor="MegaRAID"),
    VolumeInquiry(vendor="LSI"),
    VolumeInquiry(vendor="Intel", product=re.compile(r"Raid \S+ Volume$", re.IGNORECASE)),
)

# The part of the `open_error` the scan writes for a logical volume of a
# MegaRAID controller, the same in 7.4 and 7.5 (`os_linux.cpp`); only this
# part is matched, not the sentence.
MEGARAID_OPEN_ERROR: Final = "-d megaraid,N"

# The SCSI peripheral device types of a disk: 0 a direct-access block
# device, 14 a simplified direct-access device (the peripheral device
# types of SPC, as `scsicmds.cpp` of smartmontools names them).
DISK_TYPES: Final = frozenset({0, 14})


def logical_volume(vendor: str | None, product: str | None) -> bool:
    """Whether vendor and product of inquiry data name a logical volume (ADR 0028)."""
    vendor_text = " ".join((vendor or "").split())
    product_text = " ".join((product or "").split())
    if not vendor_text and not product_text:
        return False
    return any(rule.matches(vendor_text, product_text) for rule in LOGICAL_VOLUMES)


def asks_for_megaraid(open_error: str | None) -> bool:
    """Whether the scan could not open a device because it is a MegaRAID logical volume."""
    return open_error is not None and MEGARAID_OPEN_ERROR in open_error


def inquiry_text(vendor: str | None, product: str | None, *, product_label: str) -> str:
    """Return vendor and product for the detail of a skipped device."""
    parts = []
    if vendor and vendor.strip():
        parts.append(f"vendor {' '.join(vendor.split())}")
    if product and product.strip():
        parts.append(f"{product_label} {' '.join(product.split())}")
    return ", ".join(parts)
