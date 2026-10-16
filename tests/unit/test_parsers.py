# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the parsers (ADR 0004, ADR 0016).

Every recorded drive output of the test cluster is parsed, and the snapshot
is compared with the values that the recordings show (Research 06).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from pve_smart_alert.model import (
    Collection,
    DeviceAccess,
    DriveClass,
    DriveIdentity,
    Snapshot,
    WearSource,
)
from pve_smart_alert.parsers import Inquiry, ParseError, inquiry_of, parse

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
    document = {"model_name": "Some Disk"}

    with pytest.raises(ParseError, match="no parser for the protocol that smartctl did not name"):
        parse(document, access=DeviceAccess("/dev/sdb", "auto", ""), collection=COLLECTION)


def test_an_output_without_a_model_is_refused() -> None:
    document = {"device": {"protocol": "ATA"}, "serial_number": "ANON-SN-0001"}

    with pytest.raises(ParseError, match="no model name"):
        parse(document, access=DeviceAccess("/dev/sdb", "sat", "ATA"), collection=COLLECTION)


# The wear value (ADR 0021)


def test_the_snapshot_carries_the_wear_and_its_source() -> None:
    snapshot = snapshot_of("pve5", "sda")

    assert snapshot.metrics["wear.percent_used"] == 44
    assert snapshot.wear_source is WearSource.ENDURANCE_USED
    # The web interface shows 0 % for the Fanxiang S301 (Research 06).
    assert snapshot.metrics["wear.web_interface_percent_used"] == 0


def test_an_nvme_snapshot_carries_the_wear() -> None:
    snapshot = snapshot_of("pve7", "nvme1")

    assert snapshot.metrics["wear.percent_used"] == 19
    assert snapshot.wear_source is WearSource.ENDURANCE_USED


# SCSI: SAS and parallel SCSI (Research 08)

FIXTURES: Final = RECORDINGS.parent


def scsi_snapshot(path: str, document: Mapping[str, object] | None = None) -> Snapshot:
    if document is None:
        document = json.loads((FIXTURES / path).read_text(encoding="utf-8"))
    assert document is not None
    return parse(
        document,
        access=DeviceAccess("/dev/sda", "scsi", "SCSI"),
        collection=Collection(smartctl_version=(7, 4), exit_status=0),
    )


def test_a_sas_ssd_behind_an_hba() -> None:
    # The maintainer's TrueNAS host, smartmontools 7.4.
    snapshot = scsi_snapshot("hba/maintainer-truenas/sda.json")

    # The logical unit id is the WWN that lsblk shows for the drive (Q-R6).
    assert snapshot.identity == DriveIdentity(
        "NETAPP X371_SLBPE960ATE", serial="ANON-SN-0001", wwn="5000c50000000001"
    )
    assert snapshot.drive_class is DriveClass.SSD
    assert snapshot.firmware == "NA50"
    assert snapshot.capacity_bytes == 960197124096
    assert snapshot.health_passed is True
    assert snapshot.smart_available is True
    assert snapshot.smart_enabled is True
    assert snapshot.power_on_hours == 37535
    assert snapshot.power_cycles == 100
    assert snapshot.metrics == {
        "wear.percent_used": 0,
        "temperature.current": 43,
        "scsi.grown_defects": 0,
        "scsi.uncorrected_errors": 0,
    }
    # smartmontools 7.4 writes no endurance_used for SCSI.
    assert snapshot.wear_source is WearSource.ENDURANCE_INDICATOR


def test_a_drive_with_grown_defects_and_uncorrected_errors() -> None:
    snapshot = scsi_snapshot("direct/exporter-seagate-st373453lc-defects/sdb.json")

    assert snapshot.drive_class is DriveClass.HDD
    # 1 uncorrected read error and 535 uncorrected write errors; the drive
    # still reports its health as passed.
    assert snapshot.metrics["scsi.grown_defects"] == 260
    assert snapshot.metrics["scsi.uncorrected_errors"] == 536
    assert snapshot.health_passed is True
    # Its logical unit id is missing, so there is no WWN.
    assert snapshot.identity.wwn is None


def test_the_key_names_before_smartmontools_7_3() -> None:
    # `model_name` and `revision` instead of `scsi_model_name` and `scsi_revision`.
    snapshot = scsi_snapshot("direct/scrutiny-seagate-st4000nm0043/sdg.json")

    assert snapshot.identity.model == "SEAGATE ST4000NM0043"
    assert snapshot.firmware == "MS03"
    assert snapshot.metrics["scsi.grown_defects"] == 56


def test_a_value_the_drive_does_not_report_is_left_out() -> None:
    # This SAS SSD has no grown defect list, and no pending defects page.
    snapshot = scsi_snapshot("direct/libblockdev-hgst-husmr3280ass200/sdc.json")

    assert "scsi.grown_defects" not in snapshot.metrics
    assert "scsi.pending_defects" not in snapshot.metrics
    assert snapshot.last_self_test_passed is True


def test_only_the_parts_of_the_error_counter_log_the_drive_reports_add_up() -> None:
    document = {
        "device": {"protocol": "SCSI"},
        "scsi_model_name": "SEAGATE ST600MP0036",
        "scsi_error_counter_log": {
            "read": {"total_uncorrected_errors": 2},
            "write": {"total_uncorrected_errors": 3},
        },
    }

    assert scsi_snapshot("", document).metrics["scsi.uncorrected_errors"] == 5


def test_no_error_counter_log_is_not_zero_errors() -> None:
    document = {"device": {"protocol": "SCSI"}, "scsi_model_name": "SEAGATE ST600MP0036"}

    assert "scsi.uncorrected_errors" not in scsi_snapshot("", document).metrics


def test_the_pending_defects_are_read_where_the_drive_has_the_page() -> None:
    document = {
        "device": {"protocol": "SCSI"},
        "scsi_model_name": "SEAGATE ST600MP0036",
        "scsi_pending_defects": {"count": 4},
    }

    assert scsi_snapshot("", document).metrics["scsi.pending_defects"] == 4


def test_a_missing_health_verdict_is_not_a_failed_one() -> None:
    # A drive without the informational exceptions mode page (Research 08).
    document = {"device": {"protocol": "SCSI"}, "scsi_model_name": "Intel Raid 1 Volume"}

    assert scsi_snapshot("", document).health_passed is None


def test_a_failed_verdict_keeps_what_the_drive_says() -> None:
    document = {
        "device": {"protocol": "SCSI"},
        "scsi_model_name": "SEAGATE ST600MP0036",
        "smart_status": {
            "passed": False,
            "scsi": {"asc": 93, "ascq": 0, "ie_string": "FAILURE PREDICTION THRESHOLD EXCEEDED"},
        },
    }

    snapshot = scsi_snapshot("", document)

    assert snapshot.health_passed is False
    assert snapshot.health_detail == ("FAILURE PREDICTION THRESHOLD EXCEEDED (ASC 0x5d, ASCQ 0x00)")


@pytest.mark.parametrize(
    ("result", "passed"),
    [(0, True), (1, None), (2, None), (3, False), (5, False), (7, False), (15, None)],
)
def test_the_most_recent_self_test(result: int, passed: bool | None) -> None:
    # 1 and 2 are aborted tests, 15 a test in progress (SPC-3 7.2.10).
    document = {
        "device": {"protocol": "SCSI"},
        "scsi_model_name": "SEAGATE ST600MP0036",
        "scsi_self_test_0": {"result": {"value": result}},
        "scsi_self_test_1": {"result": {"value": 5}},
    }

    assert scsi_snapshot("", document).last_self_test_passed is passed


def test_endurance_used_comes_first() -> None:
    # smartmontools 7.5 writes the indicator under both keys.
    document = {
        "device": {"protocol": "SCSI"},
        "scsi_model_name": "TOSHIBA KPM5XMUG400G",
        "rotation_rate": 0,
        "scsi_percentage_used_endurance_indicator": 7,
        "endurance_used": {"current_percent": 7},
    }

    snapshot = scsi_snapshot("", document)

    assert snapshot.metrics["wear.percent_used"] == 7
    assert snapshot.wear_source is WearSource.ENDURANCE_USED


def test_a_logical_unit_id_that_is_not_naa_5_is_no_wwn() -> None:
    document = {
        "device": {"protocol": "SCSI"},
        "scsi_model_name": "HP LOGICAL VOLUME",
        "logical_unit_id": "0x600508b0000000000000000000000001",
    }

    assert scsi_snapshot("", document).identity.wwn is None


def test_a_scsi_output_without_a_model_is_refused() -> None:
    with pytest.raises(ParseError, match="no model name"):
        scsi_snapshot("", {"device": {"protocol": "SCSI"}, "serial_number": "ANON-SN-0001"})


@pytest.mark.parametrize(
    "path",
    sorted(
        str(path.relative_to(FIXTURES))
        for path in FIXTURES.rglob("*.json")
        if path.name not in ("scan.json", "recording.json", "lsblk.json")
        and '"protocol": "SCSI"' in path.read_text(encoding="utf-8")
        # A RAID volume with a temperature of 0, not a drive: discovery
        # skips it as a logical volume before it is parsed (ADR 0028).
        and "intel-rst" not in path.parts
    ),
)
def test_every_recorded_scsi_drive_is_parsed(path: str) -> None:
    snapshot = scsi_snapshot(path)

    assert (snapshot.identity.serial or "").startswith("ANON-SN-")
    assert snapshot.metrics["temperature.current"] > 0


def test_the_inquiry_data_of_a_raid_volume_are_read() -> None:
    # The Intel RAID 1 volume of Scrutiny, smartmontools 7.0, with the keys
    # `vendor` and `product` of 7.0 to 7.2. Discovery takes them for a
    # logical volume and skips it (ADR 0028, tests/unit/test_discovery.py).
    document = json.loads(
        (FIXTURES / "intel-rst/scrutiny-raid1-volume/sdb.json").read_text(encoding="utf-8")
    )

    assert inquiry_of(document) == Inquiry(
        vendor="Intel", product="Raid 1 Volume", peripheral_type=0, peripheral_name="disk"
    )


def test_a_raid_volume_still_parses_like_a_drive() -> None:
    # The parser does not judge what a device is: no SMART support key and
    # a temperature of 0 make a snapshot without findings.
    snapshot = scsi_snapshot("intel-rst/scrutiny-raid1-volume/sdb.json")

    assert snapshot.identity.model == "Intel Raid 1 Volume"
    assert snapshot.smart_available is None
    assert snapshot.health_passed is None
    assert snapshot.metrics == {"temperature.current": 0}


def test_the_inquiry_data_of_smartmontools_7_3_are_read() -> None:
    document = json.loads(
        (FIXTURES / "direct/libblockdev-seagate-st600mp0036/sdb.json").read_text(encoding="utf-8")
    )

    inquiry = inquiry_of(document)

    assert (inquiry.vendor, inquiry.product) == ("SEAGATE", "ST600MP0036")
    assert inquiry.peripheral_type == 0
