# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the parsers (ADR 0004, ADR 0016).

Every recorded drive output of the test cluster is parsed, and the snapshot
is compared with the values that the recordings show (Research 06).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest

from pve_smart_alert.model import (
    Collection,
    DeviceAccess,
    DriveClass,
    DriveIdentity,
    Snapshot,
)
from pve_smart_alert.parsers import ParseError, parse

RECORDINGS: Final = Path(__file__).resolve().parent.parent / "fixtures" / "smartctl" / "direct"
COLLECTION: Final = Collection(smartctl_version=(7, 5), exit_status=0)


def recorded(recording: str, device: str) -> dict[str, object]:
    path = RECORDINGS / f"test-cluster-{recording}" / f"{device}.json"
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def snapshot_of(recording: str, device: str) -> Snapshot:
    document = recorded(recording, device)
    access = document["device"]
    assert isinstance(access, dict)
    return parse(
        document,
        access=DeviceAccess(access["name"], access["type"], access["protocol"]),
        collection=COLLECTION,
    )


# ATA


def test_the_fanxiang_s301() -> None:
    snapshot = snapshot_of("pve5", "sda")

    # The anonymized WWN: naa 5, the oui of the drive, the number 1.
    assert snapshot.identity == DriveIdentity(
        "Fanxiang S301 256GB", serial="ANON-SN-0001", wwn="50c82d5000000001"
    )
    assert snapshot.drive_class is DriveClass.SSD
    assert snapshot.firmware == "SN17721"
    assert snapshot.capacity_bytes == 256060514304
    assert snapshot.power_on_hours == 7109
    assert snapshot.power_cycles == 39
    assert snapshot.smart_available is True
    assert snapshot.smart_enabled is True
    assert snapshot.health_passed is True
    assert snapshot.last_self_test_passed is True
    assert snapshot.metrics["ata.attr.5.raw"] == 0
    assert snapshot.metrics["ata.error_log.count"] == 0


def test_the_temperature_is_not_the_packed_raw_value() -> None:
    # Attribute 194 of the Fanxiang S301 has the raw value 214750527538
    # (Research 06); the temperature is 50 °C.
    snapshot = snapshot_of("pve5", "sda")

    assert snapshot.metrics["ata.attr.194.raw"] == 214750527538
    assert snapshot.metrics["temperature.current"] == 50


def test_a_threshold_of_zero_never_fails() -> None:
    # Attribute 187 of the Fanxiang S301: worst 0, threshold 0 (Research 06).
    snapshot = snapshot_of("pve5", "sda")

    assert snapshot.metrics["ata.attr.187.value"] == 100
    assert snapshot.failing_attributes == ()


def test_the_wwn_is_written_as_hexadecimal_digits() -> None:
    # naa 5, oui 9528 (Samsung) and the anonymized number 1.
    assert snapshot_of("pve7", "sda").identity.wwn == "5002538000000001"


@pytest.mark.parametrize(
    ("recording", "model", "firmware", "hours", "temperature", "self_test"),
    [
        ("pve6", "Samsung SSD 750 EVO 500GB", "MAT01B6Q", 61398, 34, True),
        ("pve7", "Samsung SSD 850 EVO 250GB", "EMT01B6Q", 54558, 36, None),
    ],
)
def test_the_samsung_sata_drives(
    recording: str,
    model: str,
    firmware: str,
    hours: int,
    temperature: int,
    self_test: bool | None,
) -> None:
    snapshot = snapshot_of(recording, "sda")

    assert snapshot.identity.model == model
    assert snapshot.drive_class is DriveClass.SSD
    assert snapshot.firmware == firmware
    assert snapshot.power_on_hours == hours
    assert snapshot.metrics["temperature.current"] == temperature
    # The 850 EVO has no self-test in its log.
    assert snapshot.last_self_test_passed is self_test
    assert snapshot.failing_attributes == ()


def test_an_ata_drive_without_a_rotation_rate_counts_as_a_hard_disk() -> None:
    document = recorded("pve7", "sda")
    del document["rotation_rate"]

    snapshot = parse(document, access=DeviceAccess("/dev/sda", "sat", "ATA"), collection=COLLECTION)

    assert snapshot.drive_class is DriveClass.HDD


def test_an_attribute_failing_now_is_named() -> None:
    document = recorded("pve7", "sda")
    table = document["ata_smart_attributes"]
    assert isinstance(table, dict)
    attribute = table["table"][0]
    attribute["when_failed"] = "now"

    snapshot = parse(document, access=DeviceAccess("/dev/sda", "sat", "ATA"), collection=COLLECTION)

    assert [failing.id for failing in snapshot.failing_attributes] == [attribute["id"]]
    assert snapshot.failing_attributes[0].prefailure is attribute["flags"]["prefailure"]


# NVMe


@pytest.mark.parametrize(
    ("recording", "device", "model", "used", "threshold", "errors", "hours"),
    [
        ("pve6", "nvme0", "WDC PC SN720 SDAPNTW-512G-1016", 0, 10, 0, 36751),
        ("pve7", "nvme0", "SAMSUNG MZVLW256HEHP-000L2", 2, 10, 2934, 9763),
        ("pve7", "nvme1", "SAMSUNG MZVLW256HEHP-000H1", 19, 5, 3626, 6616),
    ],
)
def test_the_nvme_drives(
    recording: str,
    device: str,
    model: str,
    used: int,
    threshold: int,
    errors: int,
    hours: int,
) -> None:
    snapshot = snapshot_of(recording, device)

    assert snapshot.identity.model == model
    assert snapshot.identity.stable
    assert snapshot.identity.wwn is None
    assert snapshot.drive_class is DriveClass.NVME
    assert snapshot.nvme_critical_warning == 0
    assert snapshot.power_on_hours == hours
    assert snapshot.metrics["nvme.percentage_used"] == used
    assert snapshot.metrics["nvme.available_spare"] == 100
    assert snapshot.metrics["nvme.available_spare_threshold"] == threshold
    assert snapshot.metrics["nvme.media_errors"] == 0
    assert snapshot.metrics["nvme.error_log_entries"] == errors


def test_the_temperature_limits_of_an_nvme_drive_are_kept() -> None:
    snapshot = snapshot_of("pve7", "nvme0")

    assert snapshot.metrics["temperature.current"] == 45
    assert snapshot.metrics["temperature.limit.warning"] == 69
    assert snapshot.metrics["temperature.limit.critical"] == 72


def test_an_nvme_drive_without_a_self_test_has_no_result() -> None:
    assert snapshot_of("pve7", "nvme0").last_self_test_passed is None
    # The SN720 has one, completed without error.
    assert snapshot_of("pve6", "nvme0").last_self_test_passed is True


# What the parsers do not know


def test_missing_sections_leave_the_values_out() -> None:
    # Output with missing keys is accepted (FR-206).
    document: dict[str, object] = {
        "device": {"name": "/dev/sdb", "type": "sat", "protocol": "ATA"},
        "model_name": "Some Drive",
    }

    snapshot = parse(document, access=DeviceAccess("/dev/sdb", "sat", "ATA"), collection=COLLECTION)

    assert snapshot.metrics == {}
    assert snapshot.identity == DriveIdentity("Some Drive")
    assert snapshot.health_passed is None


def test_a_protocol_without_a_parser_is_refused() -> None:
    document = {"device": {"protocol": "SCSI"}, "model_name": "Some Disk"}

    with pytest.raises(ParseError, match="no parser for the protocol SCSI"):
        parse(document, access=DeviceAccess("/dev/sdb", "scsi", "SCSI"), collection=COLLECTION)


def test_an_output_without_a_model_is_refused() -> None:
    document = {"device": {"protocol": "ATA"}, "serial_number": "ANON-SN-0001"}

    with pytest.raises(ParseError, match="no model name"):
        parse(document, access=DeviceAccess("/dev/sdb", "sat", "ATA"), collection=COLLECTION)
