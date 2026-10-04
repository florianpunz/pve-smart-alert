# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the notification model."""

from __future__ import annotations

from pve_smart_alert.model import (
    MAX_FIELD_VALUE,
    NOTIFICATION_TYPE,
    PVE_SEVERITY,
    SEVERITY_FOR_PVE,
    EventType,
    Notification,
    PveSeverity,
    Severity,
    node_name,
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
