# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the anonymization of recordings (ADR 0023).

The identifiers in these tests are made up in the form of real ones; none of
them belongs to a drive.
"""

from __future__ import annotations

import copy
import json
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
from pve_smart_alert.recording import Recording, anonymize

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


def test_two_drives_read_through_one_device_keep_each_output() -> None:
    # Every drive behind a MegaRAID controller is read through the same
    # device with a different smartctl type. The fixture names each file
    # after the device, so without a difference the second output overwrote
    # the first and the fixture lost a drive (ADR 0023).
    first = copy.deepcopy(SATA)
    second = copy.deepcopy(NVME)
    first["device"] = {"name": "/dev/sda", "type": "megaraid,8", "protocol": "ATA"}
    second["device"] = {"name": "/dev/sda", "type": "megaraid,14", "protocol": "ATA"}
    recording = Recording(
        node="pve9", collected=None, collected_with="test", scan=None, scan_exit=None
    )
    recording.drives["sda-8"] = first
    recording.drives["sda-14"] = second
    recording.calls["sda-8"] = ("/dev/sda", "megaraid,8")
    recording.calls["sda-14"] = ("/dev/sda", "megaraid,14")

    files = anonymize(
        recording, origin="Test", license_id="AGPL-3.0-or-later", anonymized_with="test"
    )

    metadata = files["recording.json"]
    assert isinstance(metadata, dict)
    listed = metadata["files"]
    assert isinstance(listed, list)
    entries = [entry for entry in listed if isinstance(entry, dict) and entry.get("type")]
    assert len(entries) == 2
    assert len({entry["file"] for entry in entries}) == 2
    for entry in entries:
        drive = files[entry["file"]]
        assert isinstance(drive, dict)
        assert drive["model_name"] == entry["model"]


def test_a_kernel_name_with_a_path_is_kept() -> None:
    # A kernel or controller node names no drive: the path, the letters and
    # the digits are kept, whether or not the name has a second slash
    # (ADR 0023, ADR 0039).
    anonymizer = Anonymizer()

    for name in ("/dev/sda", "/dev/nvme0n1", "/dev/bus/6", "/dev/bsg/sssraid0", "/dev/dm-0"):
        assert anonymizer.learn_device(name) == name


def test_a_link_name_under_dev_disk_is_replaced() -> None:
    # A link under /dev/disk/ can hold the serial number of the drive in its
    # name, so the name is replaced like the value it holds (ADR 0039).
    anonymizer = Anonymizer()

    assert anonymizer.learn_device("/dev/disk/by-id/ata-Samsung_SSD_1234") == "/dev/anon1"


def test_a_drive_named_scan_does_not_overwrite_the_scan() -> None:
    # `scan`, `lsblk` and `recording` are the names of the other files of a
    # fixture. A drive whose device name is one of them gets a numbered file
    # name instead of overwriting that file (ADR 0023).
    drive = copy.deepcopy(SATA)
    drive["device"] = {"name": "/dev/scan", "type": "sat", "protocol": "ATA"}
    recording = Recording(
        node="pve9",
        collected=None,
        collected_with="test",
        scan={"devices": [{"name": "/dev/scan", "type": "sat"}]},
        scan_exit=0,
    )
    recording.drives["scan"] = drive
    recording.calls["scan"] = ("/dev/scan", "sat")

    files = anonymize(
        recording, origin="Test", license_id="AGPL-3.0-or-later", anonymized_with="test"
    )

    scan = files["scan.json"]
    assert isinstance(scan, dict)
    assert "model_name" not in scan
    assert isinstance(scan.get("devices"), list)
    drive_file = files["scan-2.json"]
    assert isinstance(drive_file, dict)
    assert drive_file["model_name"] == SATA["model_name"]


def test_the_free_text_of_the_metadata_is_anonymized() -> None:
    # `origin`, `collected_with`, `controller` and the source of an import
    # are free text. A serial number or WWN pasted into them is replaced
    # like any other text (ADR 0023).
    recording = Recording(
        node="pve9",
        collected=None,
        collected_with="recorded by hand on /dev/sda, serial S2R5NX0H123456A",
        scan=None,
        scan_exit=None,
        controller="LSI SAS2308, address 0x5002538e40a1b2c3",
    )
    recording.drives["sda"] = copy.deepcopy(SATA)

    files = anonymize(
        recording, origin="Test", license_id="AGPL-3.0-or-later", anonymized_with="test"
    )

    text = json.dumps(files["recording.json"])
    assert "S2R5NX0H123456A" not in text
    assert "5002538e40a1b2c3" not in text


def test_a_serial_number_with_whitespace_is_replaced_in_its_udev_form() -> None:
    # An ATA serial number may contain spaces; udev writes a space as an
    # underscore in the by-id link and in the `id` and `id-link` of lsblk
    # (ADR 0023).
    drive = copy.deepcopy(SATA)
    drive["serial_number"] = "S2R5 NX0H 1234A"
    anonymizer = Anonymizer()
    anonymizer.learn(drive)

    anonymized = anonymizer.document({"id": "ata-Samsung_SSD_850_EVO_250GB_S2R5_NX0H_1234A"})

    assert anonymized == {"id": "ata-Samsung_SSD_850_EVO_250GB_ANON-SN-0001"}


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


# The output of lsblk (ADR 0023)


def lsblk_of(*devices: Mapping[str, object]) -> dict[str, object]:
    return {"blockdevices": list(devices)}


SATA_DISK: Final[dict[str, object]] = {
    "name": "sda",
    "type": "disk",
    "serial": "S2R5NX0H123456A",
    "wwn": "0x5002538e40a1b2c3",
    "id": "Samsung_SSD_850_EVO_250GB_S2R5NX0H123456A",
    "id-link": "wwn-0x5002538e40a1b2c3",
    "ptuuid": "4f8c2c1e-0b3a-4b6e-9d2f-1c0a5e7b9d31",
    "children": [
        {
            "name": "sda3",
            "type": "part",
            "wwn": "0x5002538e40a1b2c3",
            "uuid": "Xy12Ab-cD34-eF56-gH78-iJ90-kL12-mN34oP",
            "partuuid": "9a8b7c6d-5e4f-3a2b-1c0d-9e8f7a6b5c4d",
            "fstype": "LVM2_member",
        }
    ],
}


def test_lsblk_gets_the_placeholders_of_the_scan() -> None:
    anonymizer = anonymizer_of(SATA)

    anonymized = anonymizer.lsblk(lsblk_of(SATA_DISK))

    assert isinstance(anonymized, dict)
    disk = anonymized["blockdevices"][0]
    assert disk["serial"] == "ANON-SN-0001"
    assert disk["wwn"] == "0x5002538000000001"
    assert disk["id"] == "Samsung_SSD_850_EVO_250GB_ANON-SN-0001"
    assert disk["id-link"] == "wwn-0x5002538000000001"
    assert disk["children"][0]["wwn"] == "0x5002538000000001"
    anonymizer.check(anonymized, name="lsblk.json")


def test_a_uuid_becomes_a_counter_in_its_notation() -> None:
    anonymizer = anonymizer_of(SATA)

    anonymized = anonymizer.lsblk(lsblk_of(SATA_DISK))

    assert isinstance(anonymized, dict)
    disk = anonymized["blockdevices"][0]
    assert disk["ptuuid"] == "00000000-0000-0000-0000-000000000001"
    assert disk["children"][0]["uuid"] == "000000-0000-0000-0000-0000-0000-000002"
    assert disk["children"][0]["partuuid"] == "00000000-0000-0000-0000-000000000003"
    # What is not an identifier stays.
    assert disk["children"][0]["fstype"] == "LVM2_member"


def test_a_drive_only_lsblk_shows_continues_the_counters() -> None:
    # Such as the USB drive of a KVM-over-IP device (Research 06).
    usb = {"name": "sdb", "type": "disk", "serial": "USB0123456789", "wwn": None}
    anonymizer = anonymizer_of(SATA, NVME)

    anonymized = anonymizer.lsblk(lsblk_of(SATA_DISK, usb))

    assert isinstance(anonymized, dict)
    assert anonymized["blockdevices"][1]["serial"] == "ANON-SN-0003"


def test_an_nguid_keeps_the_vendor_part_of_its_eui64() -> None:
    # The first half is vendor-specific, the second half the EUI-64.
    nvme = {"name": "nvme0n1", "type": "disk", "wwn": "eui.e8238fa6bf5300010025385b71b02a7f"}
    anonymizer = anonymizer_of(NVME)

    anonymized = anonymizer.lsblk(lsblk_of(nvme))

    assert isinstance(anonymized, dict)
    assert anonymized["blockdevices"][0]["wwn"] == "eui.00000000000000010025380000000001"
    anonymizer.check(anonymized, name="lsblk.json")


def test_a_wwn_in_an_unknown_form_fails_the_check() -> None:
    disk = {"name": "sdc", "type": "disk", "wwn": "naa.5002538e40a1b2c3"}
    anonymizer = anonymizer_of(SATA)

    anonymized = anonymizer.lsblk(lsblk_of(disk))

    with pytest.raises(AnonymizationError, match=r"lsblk\.json still contains a real value: WWN"):
        anonymizer.check(anonymized, name="lsblk.json")


def test_a_real_uuid_left_in_a_text_fails_the_check() -> None:
    anonymizer = anonymizer_of(SATA)
    anonymizer.lsblk(lsblk_of(SATA_DISK))

    with pytest.raises(AnonymizationError, match="UUID"):
        anonymizer.check({"note": "4f8c2c1e-0b3a-4b6e-9d2f-1c0a5e7b9d31"}, name="other.json")


# SCSI drives: the logical unit id and the SAS addresses (ADR 0026)

SAS: Final[dict[str, object]] = {
    "device": {"name": "/dev/sdc", "type": "scsi", "protocol": "SCSI"},
    "scsi_model_name": "HGST HUSMR3280ASS200",
    "serial_number": "0HWZ3X1A",
    "logical_unit_id": "0x5000cca04eb1c2d4",
    "scsi_sas_port_0": {
        "phy_0": {
            "sas_address": "0x5000cca04eb1c2d5",
            "attached_sas_address": "0x500605b00c1d2e30",
        },
        "phy_1": {"sas_address": "0x5000cca04eb1c2d6", "attached_sas_address": "0x0"},
    },
}


def test_a_logical_unit_id_of_naa_5_is_a_wwn() -> None:
    anonymizer = anonymizer_of(SAS)

    sas = anonymizer.drive(SAS)
    # lsblk writes the same name as the WWN of the block device, so both get
    # the same placeholder.
    lsblk = anonymizer.lsblk({"blockdevices": [{"name": "sdc", "wwn": "0x5000cca04eb1c2d4"}]})

    assert sas["logical_unit_id"] == "0x5000cca000000001"
    assert lsblk == {"blockdevices": [{"name": "sdc", "wwn": "0x5000cca000000001"}]}


def test_the_sas_addresses_continue_the_counter_and_a_zero_address_stays() -> None:
    sas = anonymizer_of(SAS).drive(SAS)

    port = sas["scsi_sas_port_0"]
    assert isinstance(port, dict)
    assert port["phy_0"] == {
        "sas_address": "0x5000cca000000002",
        "attached_sas_address": "0x500605b000000003",
    }
    assert port["phy_1"] == {"sas_address": "0x5000cca000000004", "attached_sas_address": "0x0"}


def test_a_drive_with_a_zero_sas_address_passes_the_check() -> None:
    # A phy that is attached to nothing is common on a SAS drive; its zero
    # address must not stop dump-fixture.
    anonymizer = anonymizer_of(SAS)

    anonymizer.check(anonymizer.drive(SAS), name="sdc.json")


def test_an_naa_6_name_keeps_its_authority_and_vendor() -> None:
    drive = {**SAS, "logical_unit_id": "0x600508b1001c4d3e2f1a0b9c8d7e6f50"}

    anonymized = anonymizer_of(drive).drive(drive)

    assert anonymized["logical_unit_id"] == "0x600508b" + "1".zfill(25)


def test_a_name_of_another_form_becomes_a_counter_in_its_digits() -> None:
    drive = {**SAS, "logical_unit_id": "0x1234567890abcdef"}

    anonymized = anonymizer_of(drive).drive(drive)

    assert anonymized["logical_unit_id"] == "0x0000000000000001"


def test_the_logical_unit_id_is_replaced_in_texts() -> None:
    anonymizer = anonymizer_of(SAS)

    note = anonymizer.document({"note": "Logical Unit id: 0x5000CCA04EB1C2D4"})

    assert note == {"note": "Logical Unit id: 0x5000cca000000001"}


def test_a_logical_unit_id_in_an_unknown_form_is_refused() -> None:
    drive = {**SAS, "logical_unit_id": "naa.5000cca04eb1c2d4"}

    with pytest.raises(AnonymizationError, match="logical_unit_id in an unknown form"):
        anonymizer_of(drive)


def test_a_real_logical_unit_id_that_is_left_fails_the_check() -> None:
    anonymizer = anonymizer_of(SAS)
    leak = {**anonymizer.drive(SAS), "logical_unit_id": "0x5000cca04eb1c2d4"}

    with pytest.raises(AnonymizationError, match="real value: WWN, NAA name"):
        anonymizer.check(leak, name="sdc.json")
