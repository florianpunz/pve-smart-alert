# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the wear value and its source (ADR 0021, FR-312).

The recorded drives of the test cluster give the values of Research 06; the
order of the sources is tested by removing a source from a recording.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest

from pve_smart_alert.model import WearSource
from pve_smart_alert.parsers.wear import (
    Wear,
    ata_wear,
    device_statistics_wear,
    nvme_wear,
    vendor_attribute_wear,
)

RECORDINGS: Final = Path(__file__).resolve().parent.parent / "fixtures" / "smartctl" / "direct"


def recorded(node: str, device: str, prefix: str = "test-cluster") -> dict[str, object]:
    path = RECORDINGS / f"{prefix}-{node}" / f"{device}.json"
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def attributes(*named: tuple[int, str, int]) -> dict[str, object]:
    """Return a drive output with these attributes: ID, name, normalized value."""
    return {
        "ata_smart_attributes": {
            "table": [{"id": number, "name": name, "value": value} for number, name, value in named]
        }
    }


# The recordings (Research 06)


@pytest.mark.parametrize(
    ("node", "device", "expected"),
    [
        # The Fanxiang S301: 44 % by the standard, 0 % in the web interface.
        ("pve5", "sda", Wear(44, WearSource.ENDURANCE_USED, 0)),
        # The Samsung SSDs have no device statistics (Research 06), so the
        # value of smartmontools is a guess from a vendor attribute.
        ("pve6", "sda", Wear(35, WearSource.VENDOR_ATTRIBUTE, 35)),
        ("pve7", "sda", Wear(12, WearSource.VENDOR_ATTRIBUTE, 12)),
    ],
)
def test_the_recorded_sata_drives(node: str, device: str, expected: Wear) -> None:
    assert ata_wear(recorded(node, device)) == expected


def test_the_intenso_ssd_of_the_standalone_host() -> None:
    # The API of pve1 returns 100, so the web interface shows 100 - 100 = 0 %,
    # while the endurance indicator of the drive says 3 %.
    drive = recorded("pve1", "sda", prefix="standalone")

    assert ata_wear(drive) == Wear(3, WearSource.ENDURANCE_USED, 0)


@pytest.mark.parametrize(
    ("node", "device", "expected"),
    [
        ("pve6", "nvme0", Wear(0, WearSource.ENDURANCE_USED, 0)),
        ("pve7", "nvme0", Wear(2, WearSource.ENDURANCE_USED, 2)),
        ("pve7", "nvme1", Wear(19, WearSource.ENDURANCE_USED, 19)),
    ],
)
def test_the_recorded_nvme_drives(node: str, device: str, expected: Wear) -> None:
    assert nvme_wear(recorded(node, device)) == expected


# The order of the sources (ADR 0021)


def test_without_endurance_used_the_device_statistics_count() -> None:
    # As on a host with smartmontools 7.4.
    drive = recorded("pve5", "sda")
    del drive["endurance_used"]

    assert ata_wear(drive) == Wear(44, WearSource.DEVICE_STATISTICS, 0)


def test_the_vendor_attribute_is_the_last_source() -> None:
    # The Samsung SSD 850 EVO has no device statistics (Research 06).
    drive = recorded("pve7", "sda")
    del drive["endurance_used"]

    assert ata_wear(drive) == Wear(12, WearSource.VENDOR_ATTRIBUTE, 12)


def test_without_device_statistics_the_guess_is_a_vendor_attribute() -> None:
    # The acceptance of M3 on the standalone host: with `detail = "basic"`,
    # smartctl reads no device statistics and keeps its guess from the
    # attribute. The guess is used, but named for what it is (Research 03).
    drive = recorded("pve1", "sda", prefix="standalone")
    del drive["ata_device_statistics"]
    drive["endurance_used"] = {"current_percent": 0}

    assert ata_wear(drive) == Wear(0, WearSource.VENDOR_ATTRIBUTE, 0)


def test_a_guess_from_an_attribute_the_web_interface_does_not_read() -> None:
    # smartmontools guesses from "SSD_Life_Left" and "Wear_Leveling"
    # attributes, the web interface from its own longer list; a drive can
    # name an attribute of the first kind only.
    drive = attributes((177, "Wear_Leveling", 90))
    drive["endurance_used"] = {"current_percent": 10}

    assert ata_wear(drive) == Wear(10, WearSource.VENDOR_ATTRIBUTE, None)


def test_an_nvme_drive_falls_back_to_its_health_log() -> None:
    drive = recorded("pve7", "nvme1")
    del drive["endurance_used"]

    assert nvme_wear(drive) == Wear(19, WearSource.HEALTH_LOG, 19)


def test_a_drive_without_any_source_has_no_wear() -> None:
    assert ata_wear({}) == Wear()
    assert nvme_wear({}) == Wear()


def test_an_invalid_device_statistics_entry_is_not_used() -> None:
    drive = recorded("pve5", "sda")
    pages = drive["ata_device_statistics"]
    assert isinstance(pages, dict)
    for page in pages["pages"]:
        for entry in page["table"]:
            if entry["name"] == "Percentage Used Endurance Indicator":
                entry["flags"]["valid"] = False

    assert device_statistics_wear(drive) is None


# The list of the web interface (PVE/Diskmanage.pm)


def test_the_order_of_the_list_decides_over_the_order_of_the_attributes() -> None:
    drive = attributes((177, "Wear_Leveling_Count", 90), (233, "Media_Wearout_Indicator", 70))

    # Media_Wearout_Indicator comes first in the list of the web interface.
    assert vendor_attribute_wear(drive) == 30


def test_a_name_that_contains_a_name_of_the_list_counts() -> None:
    drive = attributes((231, "Vendor_SSD_Life_Left_Pct", 82))

    assert vendor_attribute_wear(drive) == 18


def test_a_name_with_a_slash_counts() -> None:
    drive = attributes((173, "Perc_Write/Erase_Ct_BC", 97))

    assert vendor_attribute_wear(drive) == 3


def test_an_attribute_that_is_not_on_the_list_does_not_count() -> None:
    # Attribute 231 of the Fanxiang S301 is not named (Research 06).
    drive = attributes((231, "Unknown_SSD_Attribute", 82))

    assert vendor_attribute_wear(drive) is None
