# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the models: notifications and drives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pve_smart_alert.model import (
    MAX_FIELD_VALUE,
    MAX_PRINTED,
    NOTIFICATION_TYPE,
    PVE_SEVERITY,
    SEVERITY_FOR_PVE,
    Collection,
    DeviceAccess,
    DriveClass,
    DriveIdentity,
    EventType,
    Location,
    Membership,
    Notification,
    PveSeverity,
    Severity,
    Snapshot,
    WearSource,
    behind_controller,
    exact_string,
    is_cciss_type,
    node_name,
    pass_through_id,
    printed,
    sanitize_field_value,
)


def test_every_severity_of_the_tool_has_a_proxmox_severity() -> None:
    assert set(PVE_SEVERITY) == set(Severity)


def test_severity_mapping_follows_the_decision_record() -> None:
    assert PVE_SEVERITY[Severity.INFO] is PveSeverity.INFO
    assert PVE_SEVERITY[Severity.NOTICE] is PveSeverity.NOTICE
    assert PVE_SEVERITY[Severity.WARNING] is PveSeverity.WARNING
    assert PVE_SEVERITY[Severity.CRITICAL] is PveSeverity.ERROR


def test_a_name_of_proxmox_leads_back_to_the_severity_of_the_tool() -> None:
    # `test-notification --severity error` is the way back (FR-520).
    assert set(SEVERITY_FOR_PVE) == set(PveSeverity)
    for severity, pve in PVE_SEVERITY.items():
        assert SEVERITY_FOR_PVE[pve] is severity
    assert SEVERITY_FOR_PVE[PveSeverity.ERROR] is Severity.CRITICAL


def test_event_types_are_the_documented_ones() -> None:
    assert [event.value for event in EventType] == [
        "problem",
        "escalated",
        "worsened",
        "reminder",
        "recovered",
        "missing",
        "summary",
        "first-run",
        "tool",
        "test",
    ]


def test_sanitize_replaces_commas() -> None:
    # An exact matcher splits its value list on commas (ADR 0008).
    assert sanitize_field_value("Samsung SSD, 1TB") == "Samsung SSD; 1TB"


def test_sanitize_replaces_control_characters() -> None:
    assert sanitize_field_value("first\nsecond\tthird") == "first second third"
    assert sanitize_field_value("bell\x07") == "bell"
    assert sanitize_field_value("delete\x7fme") == "delete me"


def test_sanitize_collapses_whitespace_and_strips() -> None:
    assert sanitize_field_value("  a   b  ") == "a b"


def test_sanitize_cuts_long_values() -> None:
    long_value = "s" * (MAX_FIELD_VALUE + 50)
    assert len(sanitize_field_value(long_value)) == MAX_FIELD_VALUE


def test_sanitize_keeps_an_empty_value_empty() -> None:
    assert sanitize_field_value("   ") == ""


def test_a_cut_value_carries_a_mark() -> None:
    # A copy of a cut value is not the value (ADR 0036).
    assert printed("s" * (MAX_PRINTED + 50), limit=MAX_PRINTED) == "s" * MAX_PRINTED + "…"
    assert printed("short", limit=MAX_PRINTED) == "short"


def test_the_exact_form_escapes_what_cannot_be_printed() -> None:
    assert exact_string('ACME\x01"X" 8TB') == '"ACME\\u0001\\"X\\" 8TB"'
    assert exact_string("back\\slash") == '"back\\\\slash"'


def test_a_field_value_of_control_characters_only_is_escaped() -> None:
    # Cleaning would leave nothing, and a field that is left out cannot be
    # matched at all (ADR 0036).
    assert sanitize_field_value("\x01") == '"\\u0001"'


def test_sanitize_keeps_characters_that_are_not_ascii() -> None:
    assert sanitize_field_value("Festplatte Größe") == "Festplatte Größe"


def test_fields_always_carry_type_and_hostname() -> None:
    notification = Notification(
        event=EventType.TEST,
        severity=Severity.INFO,
        node="pve1",
        subject="subject",
        body="body",
    )

    assert notification.fields_for() == {"type": NOTIFICATION_TYPE, "hostname": "pve1"}


def test_fields_keep_the_fields_of_the_drive() -> None:
    notification = Notification(
        event=EventType.PROBLEM,
        severity=Severity.WARNING,
        node="pve1",
        subject="subject",
        body="body",
        fields={"event": "problem", "device": "/dev/sdb", "serial": "S5Y1NX0R000001A"},
    )

    fields = notification.fields_for()

    assert fields["event"] == "problem"
    assert fields["device"] == "/dev/sdb"
    assert fields["serial"] == "S5Y1NX0R000001A"


def test_fields_cannot_replace_type_and_hostname() -> None:
    notification = Notification(
        event=EventType.TEST,
        severity=Severity.INFO,
        node="pve1",
        subject="subject",
        body="body",
        fields={"type": "other", "hostname": "elsewhere"},
    )

    fields = notification.fields_for()

    assert fields["type"] == NOTIFICATION_TYPE
    assert fields["hostname"] == "pve1"


def test_fields_are_sanitized() -> None:
    notification = Notification(
        event=EventType.PROBLEM,
        severity=Severity.WARNING,
        node="pve1",
        subject="subject",
        body="body",
        fields={"model": "Samsung SSD,\n1TB"},
    )

    assert notification.fields_for()["model"] == "Samsung SSD; 1TB"


def test_node_name_is_the_short_host_name() -> None:
    assert node_name("pve1") == "pve1"
    assert node_name("pve1.lab.example.com") == "pve1"


# The drive model (ARCHITECTURE.md section 4)


RECORDED = Path(__file__).resolve().parent.parent / "fixtures" / "smartctl" / "direct"


def recorded_identity(recording: str, device: str) -> DriveIdentity:
    """Return the identity of one drive of the anonymized recordings."""
    drive = json.loads((RECORDED / recording / f"{device}.json").read_text(encoding="utf-8"))
    return DriveIdentity.of(drive["model_name"], serial=drive["serial_number"])


def test_reported_values_are_normalized() -> None:
    identity = DriveIdentity.of("  Samsung  SSD 850 EVO\t250GB ", serial=" ANON-SN-0001 ")

    assert identity == DriveIdentity("Samsung SSD 850 EVO 250GB", serial="ANON-SN-0001")


@pytest.mark.parametrize("serial", [None, "", "   "])
def test_a_missing_or_empty_serial_number_is_missing(serial: str | None) -> None:
    assert DriveIdentity.of("QEMU HARDDISK", serial=serial).serial is None


def test_a_wwn_is_written_as_lowercase_digits() -> None:
    identity = DriveIdentity.of("Model", wwn="0x5002538E40000001")

    assert identity.wwn == "5002538e40000001"


def test_an_identity_is_stable_with_a_serial_number_or_a_wwn() -> None:
    # Without either, the drive is exempt from missing-drive detection (FR-309).
    assert DriveIdentity.of("Model", serial="ANON-SN-0001").stable
    assert DriveIdentity.of("Model", wwn="5002538000000001").stable
    assert not DriveIdentity.of("Model").stable


def test_the_path_is_not_part_of_the_identity() -> None:
    # FR-105: the same drive behind another device node is the same drive.
    identity = recorded_identity("test-cluster-pve7", "sda")
    collection = Collection(smartctl_version=(7, 5), exit_status=0)
    first = Snapshot(identity, DeviceAccess("/dev/sda", "sat", "ATA"), DriveClass.SSD, collection)
    second = Snapshot(identity, DeviceAccess("/dev/sdb", "sat", "ATA"), DriveClass.SSD, collection)

    assert first.identity == second.identity
    assert first.access != second.access


def test_the_recorded_drives_have_stable_and_distinct_identities() -> None:
    identities = [
        recorded_identity("test-cluster-pve7", device) for device in ("sda", "nvme0", "nvme1")
    ]

    assert all(identity.stable for identity in identities)
    assert len(set(identities)) == 3
    assert identities[0] == DriveIdentity("Samsung SSD 850 EVO 250GB", serial="ANON-SN-0001")


def test_the_drive_classes_are_those_of_the_check_catalog() -> None:
    assert [drive_class.value for drive_class in DriveClass] == ["hdd", "ssd", "nvme"]


def test_the_wear_sources_follow_the_order_of_adr_0021() -> None:
    assert [source.value for source in WearSource] == [
        "endurance_used",
        "device statistics",
        "health log",
        "endurance indicator",
        "vendor attribute",
    ]


def test_a_snapshot_knows_only_what_it_is_given() -> None:
    # Missing values are not applicable, never guessed (FR-206).
    snapshot = Snapshot(
        DriveIdentity.of("Model", serial="ANON-SN-0001"),
        DeviceAccess("/dev/nvme0", "nvme", "NVMe"),
        DriveClass.NVME,
        Collection(smartctl_version=(7, 5), exit_status=0),
    )

    assert snapshot.metrics == {}
    assert snapshot.health_passed is None
    assert snapshot.wear_source is None
    assert snapshot.membership == Membership()
    assert snapshot.location == Location()


@pytest.mark.parametrize(
    ("device_type", "device_id"),
    [
        ("megaraid,8", "8"),
        ("sat+megaraid,14", "14"),
        ("megaraid,0", "0"),
        # The drives behind an HPE Smart Array controller (ADR 0032).
        ("cciss,0", "0"),
        ("cciss,127", "127"),
        ("sat+cciss,2", "2"),
        # The documented `scsi+` forms: the SCSI pass-through itself.
        ("scsi+cciss,3", "3"),
        ("scsi+megaraid,8", "8"),
        ("sat", None),
        ("scsi", None),
        ("nvme", None),
        ("megaraid", None),
        ("megaraid,", None),
        ("sat+megaraid,x", None),
        ("cciss", None),
        ("cciss,", None),
        ("scsi+cciss", None),
    ],
)
def test_the_device_id_is_read_from_a_pass_through_type(
    device_type: str, device_id: str | None
) -> None:
    # One function for `scan`, the location of a message and the field
    # `device-id` (ADR 0028, ADR 0029, ADR 0032).
    assert pass_through_id(device_type) == device_id


@pytest.mark.parametrize(
    ("device_type", "cciss"),
    [
        ("cciss,0", True),
        ("sat+cciss,3", True),
        ("scsi+cciss,3", True),
        ("megaraid,8", False),
        ("scsi+megaraid,8", False),
        ("sat", False),
        ("cciss", False),
    ],
)
def test_a_cciss_type_is_recognized(device_type: str, cciss: bool) -> None:
    # The planner forgets the drives of a switched-off probe by their type
    # (ADR 0032).
    assert is_cciss_type(device_type) is cciss


@pytest.mark.parametrize(
    ("device_type", "behind"),
    [
        ("megaraid,8", True),
        ("sat+megaraid,14", True),
        ("cciss,0", True),
        ("scsi+cciss,3", True),
        # The other controller types of smartctl(8) (Research 04).
        ("3ware,2", True),
        ("areca,2", True),
        ("areca,1/1", True),
        ("aacraid,0,0,2", True),
        ("scsi+aacraid,1,0,4", True),
        ("hpt,1/3", True),
        ("hpt,1/2/3", True),
        ("sssraid,0,1", True),
        # `sat` with its options before the type (dev_interface.cpp of 7.5).
        ("sat,auto+aacraid,0,0,2", True),
        ("sat,12+megaraid,2", True),
        ("sat,16+cciss,0", True),
        ("sat", False),
        ("scsi", False),
        ("nvme", False),
        ("sat,12", False),
        ("areca", False),
        ("usbjmicron,0", False),
    ],
)
def test_a_type_that_reads_a_drive_behind_a_controller_is_recognized(
    device_type: str, behind: bool
) -> None:
    # What the host shows for the node of such a type is not the drive's
    # (ADR 0028).
    assert behind_controller(device_type) is behind
    # Only some of them have a device ID (ADR 0029).
    if pass_through_id(device_type) is not None:
        assert behind
