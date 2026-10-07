# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the anonymization of recordings (ADR 0023).

The identifiers in these tests are made up in the form of real ones; none of
them belongs to a drive.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Final

import pytest

from pve_smart_alert.anonymize import (
    COUNTER_LIMIT,
    AnonymizationError,
    Anonymizer,
    Eui64,
    Wwn,
)

SATA: Final[dict[str, object]] = {
    "device": {"name": "/dev/sda", "type": "sat", "protocol": "ATA"},
    "model_name": "Samsung SSD 850 EVO 250GB",
    "serial_number": "S2R5NX0H123456A",
    "wwn": {"naa": 5, "oui": 9528, "id": 0xE40A1B2C3},
    "firmware_version": "EMT02B6Q",
    "power_on_time": {"hours": 54558},
}
NVME: Final[dict[str, object]] = {
    "device": {"name": "/dev/nvme0", "type": "nvme", "protocol": "NVMe"},
    "model_name": "SAMSUNG MZVLW256HEHP-000L2",
    "serial_number": "S35ENX0J654321",
    "nvme_ieee_oui_identifier": 9528,
    "nvme_namespaces": [{"id": 1, "eui64": {"oui": 9528, "ext_id": 0x5B71B02A7F}}],
}


def anonymizer_of(*drives: Mapping[str, object]) -> Anonymizer:
    """Return an anonymizer that has learned these drives, in this order."""
    anonymizer = Anonymizer()
    for drive in drives:
        anonymizer.learn(drive)
    return anonymizer


def test_the_identifiers_become_counters_in_the_learned_order() -> None:
    anonymizer = anonymizer_of(SATA, NVME)

    sata = anonymizer.drive(SATA)
    nvme = anonymizer.drive(NVME)

    assert sata["serial_number"] == "ANON-SN-0001"
    assert nvme["serial_number"] == "ANON-SN-0002"
    # The authority and the vendor stay, the number becomes the counter.
    assert sata["wwn"] == {"naa": 5, "oui": 9528, "id": 1}
    assert nvme["nvme_namespaces"] == [{"id": 1, "eui64": {"oui": 9528, "ext_id": 1}}]


def test_everything_else_stays() -> None:
    anonymized = anonymizer_of(SATA).drive(SATA)

    unchanged = {key: value for key, value in SATA.items() if key not in ("serial_number", "wwn")}
    assert {key: anonymized[key] for key in unchanged} == unchanged


def test_the_same_value_gets_the_same_placeholder_everywhere() -> None:
    anonymizer = anonymizer_of(SATA, NVME)
    # The same drive seen a second time, and its serial number in a text.
    other = {"note": "Samsung_SSD_850_EVO_250GB_S2R5NX0H123456A"}

    assert anonymizer.drive(SATA) == anonymizer.drive(copy.deepcopy(SATA))
    assert anonymizer.document(other) == {"note": "Samsung_SSD_850_EVO_250GB_ANON-SN-0001"}


def test_the_hexadecimal_forms_are_replaced_in_texts() -> None:
    # As lsblk, udev and the web interface write them.
    anonymizer = anonymizer_of(SATA, NVME)
    texts = [
        "0x5002538e40a1b2c3",
        "wwn-0x5002538E40A1B2C3",
        "eui.0025385b71b02a7f",
        "nvme-eui.0025385b71b02a7f",
    ]

    assert anonymizer.document(texts) == [
        "0x5002538000000001",
        "wwn-0x5002538000000001",
        "eui.0025380000000001",
        "nvme-eui.0025380000000001",
    ]


def test_the_input_is_not_changed() -> None:
    before = copy.deepcopy(NVME)

    anonymizer_of(NVME).drive(NVME)

    assert before == NVME


def test_the_hexadecimal_forms_are_those_of_udev() -> None:
    assert Wwn(5, 9528, 0xE40A1B2C3).hex == "5002538e40a1b2c3"
    assert Eui64(9528, 0x5B71B02A7F).hex == "0025385b71b02a7f"


def test_an_anonymized_recording_passes_the_check() -> None:
    anonymizer = anonymizer_of(SATA, NVME)

    for drive in (SATA, NVME):
        anonymizer.check(anonymizer.drive(drive), name="drive")


@pytest.mark.parametrize(
    "leak",
    [
        {"serial_number": "S2R5NX0H123456A"},
        {"note": "s2r5nx0h123456a"},
        {"note": "wwn-0x5002538e40a1b2c3"},
        {"note": "eui.0025385b71b02a7f"},
        {"wwn": {"naa": 5, "oui": 9528, "id": 0xE40A1B2C3}},
        # An EUI-64 where the anonymizer does not expect one.
        {"eui64": {"oui": 9528, "ext_id": 0x5B71B02A7F}},
        # A serial number field it never learned.
        {"serial_number": "WD-WX11A1234567"},
    ],
)
def test_a_real_value_that_is_left_fails_the_check(leak: dict[str, object]) -> None:
    anonymizer = anonymizer_of(SATA, NVME)

    with pytest.raises(AnonymizationError) as error:
        anonymizer.check(leak, name="lsblk.json")

    # The message names the file and the kind, never the value.
    message = str(error.value)
    assert message.startswith("lsblk.json still contains a real value: ")
    assert "123456" not in message
    assert "e40a1b2c3" not in message


def test_a_short_serial_number_is_replaced_only_in_its_field() -> None:
    # "A1" could stand for anything in a text (ADR 0023).
    drive = {"serial_number": "A1", "model_name": "TOY A1 DRIVE"}

    anonymized = anonymizer_of(drive).drive(drive)

    assert anonymized == {"serial_number": "ANON-SN-0001", "model_name": "TOY A1 DRIVE"}


def test_a_drive_without_identifiers_stays_as_it_is() -> None:
    drive: dict[str, object] = {"device": {"name": "/dev/sdz"}, "smartctl": {"exit_status": 2}}

    assert anonymizer_of(drive).drive(drive) == drive


def test_more_values_than_four_digits_hold_are_refused() -> None:
    anonymizer = Anonymizer()
    for number in range(COUNTER_LIMIT):
        anonymizer.learn({"serial_number": f"SERIAL{number:05d}"})

    with pytest.raises(AnonymizationError, match="more than 9999"):
        anonymizer.learn({"serial_number": "ONE-TOO-MANY"})
