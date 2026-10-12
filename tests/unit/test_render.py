# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the renderer: subject and body against golden files (ADR 0016).

A change to the text of a notification has to update its golden file in
`tests/fixtures/golden/`. With PVE_SMART_ALERT_UPDATE_GOLDEN=1 the tests
write the files instead of comparing them; the diff is then reviewed like
any other change.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pve_smart_alert.checks import CATALOG
from pve_smart_alert.config import Config, NotifySettings
from pve_smart_alert.model import (
    FIELD_DEVICE,
    FIELD_EVENT,
    FIELD_HOSTNAME,
    FIELD_MODEL,
    FIELD_SERIAL,
    FIELD_TYPE,
    DriveClass,
    EventType,
    Notification,
    Severity,
)
from pve_smart_alert.planner import (
    DriveInfo,
    DriveMessage,
    DriveSeen,
    Item,
    MessageKind,
    Planned,
    Presence,
    SkippedSeen,
)
from pve_smart_alert.render import TEXTS, RenderContext, cluster_name, render
from pve_smart_alert.state import Access
from pve_smart_alert.tool_conditions import TOOL_CONDITIONS

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
UPDATE = os.environ.get("PVE_SMART_ALERT_UPDATE_GOLDEN") == "1"

SINCE = datetime(2026, 10, 3, 12, 34, 12, tzinfo=UTC)
CONTEXT = RenderContext(node="pve1", cluster="lab", version="0.4.0")

SSD = DriveInfo(
    key="Samsung SSD 870 EVO 1TB|ANON-SN-0001",
    name="/dev/sdb",
    type="sat",
    model="Samsung SSD 870 EVO 1TB",
    serial="ANON-SN-0001",
    wwn="5000000000000001",
    firmware="SVT02B6Q",
    capacity_bytes=1_000_204_886_016,
    drive_class=DriveClass.SSD,
    location="pci-0000:00:17.0-ata-2",
    used_by='ZFS pool "tank"',
    power_on_hours=14210,
)

REALLOCATED = Item(
    event=EventType.PROBLEM,
    check="ata.reallocated_sectors",
    severity=Severity.WARNING,
    text="8 sectors, at or above the warning threshold of 5",
    value=8,
    threshold=5,
    since=SINCE,
)


def golden(name: str, notification: Notification) -> None:
    """Compare subject and body with a golden file, or write it."""
    text = f"Subject: {notification.subject}\n\n{notification.body}"
    path = GOLDEN / f"{name}.txt"
    if UPDATE:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text


def drive_message(*items: Item, drive: DriveInfo = SSD, active: tuple[Item, ...] = ()) -> Planned:
    message = DriveMessage(drive, items, active)
    return Planned(
        MessageKind.DRIVE, message.severity, message.event, drives=(message,), changes=()
    )


def test_a_new_problem() -> None:
    notification = render(drive_message(REALLOCATED), CONTEXT)

    golden("drive-problem", notification)
    assert notification.severity is Severity.WARNING
    assert notification.event is EventType.PROBLEM


def test_an_escalation_names_the_previous_value_and_severity() -> None:
    escalated = Item(
        event=EventType.ESCALATED,
        check="ata.pending_sectors",
        severity=Severity.CRITICAL,
        text="20 sectors, at or above the critical threshold of 16",
        value=20,
        previous=3,
        threshold=16,
        since=SINCE,
        previous_severity=Severity.WARNING,
    )
    active = Item(
        event=EventType.REMINDER,
        check="ata.reallocated_sectors",
        severity=Severity.WARNING,
        text="8 sectors, at or above the warning threshold of 5",
        value=8,
        previous=8,
        threshold=5,
    )

    notification = render(drive_message(escalated, active=(active,)), CONTEXT)

    golden("drive-escalated", notification)
    assert notification.severity is Severity.CRITICAL
    assert "(previous: 3)" in notification.body


def test_a_recovery_is_info() -> None:
    recovered = Item(
        event=EventType.RECOVERED,
        check="ata.pending_sectors",
        severity=Severity.WARNING,
        text="3 sectors, at or above the warning threshold of 1",
        previous=3,
        threshold=1,
        since=SINCE,
    )

    notification = render(drive_message(recovered), CONTEXT)

    golden("drive-recovered", notification)
    assert notification.severity is Severity.INFO
    assert notification.fields[FIELD_EVENT] == "recovered"


def test_a_missing_drive_shows_what_was_known() -> None:
    gone = DriveInfo(
        key=SSD.key,
        name="/dev/sdb",
        type="sat",
        model=SSD.model,
        serial=SSD.serial,
        firmware=SSD.firmware,
        capacity_bytes=SSD.capacity_bytes,
        drive_class=DriveClass.SSD,
        present=False,
        last_seen=SINCE,
    )
    missing = Item(
        event=EventType.MISSING,
        check="drive.missing",
        severity=Severity.WARNING,
        text="the drive was not found in 2 runs in a row; last seen 2026-10-03T12:34:12Z as"
        " /dev/sdb",
        value=2,
        since=SINCE,
    )

    golden("drive-missing", render(drive_message(missing, drive=gone), CONTEXT))


def test_a_summary_lists_every_drive() -> None:
    hot = [
        DriveMessage(
            DriveInfo(
                key=f"Intenso SSD|ANON-SN-000{number}",
                name=f"/dev/sd{letter}",
                type="sat",
                model="Intenso SSD",
                serial=f"ANON-SN-000{number}",
                drive_class=DriveClass.SSD,
            ),
            (
                Item(
                    event=EventType.PROBLEM,
                    check="temperature",
                    severity=Severity.WARNING,
                    text="65 °C, at or above the warning limit of 60 °C",
                    value=65,
                    threshold=60,
                ),
            ),
        )
        for number, letter in zip(range(1, 6), "abcde", strict=True)
    ]
    planned = Planned(MessageKind.SUMMARY, Severity.WARNING, EventType.SUMMARY, drives=tuple(hot))

    notification = render(planned, CONTEXT)

    golden("summary", notification)
    # A summary carries no metadata of a single drive (ADR 0009).
    assert set(notification.fields_for()) == {FIELD_TYPE, FIELD_HOSTNAME, FIELD_EVENT}


def test_the_first_run_summary() -> None:
    planned = Planned(
        MessageKind.FIRST_RUN,
        Severity.WARNING,
        EventType.FIRST_RUN,
        drives=(
            DriveMessage(SSD, (REALLOCATED,)),
            DriveMessage(
                DriveInfo(
                    key="WDC PC SN720|ANON-SN-0002",
                    name="/dev/nvme0",
                    type="nvme",
                    model="WDC PC SN720 SDAPNTW-512G",
                    serial="ANON-SN-0002",
                    drive_class=DriveClass.NVME,
                ),
                (),
            ),
        ),
        unreadable=(
            DriveSeen(Access("/dev/sdz", "sat"), Presence.UNREADABLE, reason="No such device"),
        ),
        skipped=(SkippedSeen(Access("/dev/sdc", "sat"), "excluded", 'model = "QEMU*"'),),
    )

    notification = render(planned, CONTEXT)

    golden("first-run", notification)
    assert notification.event is EventType.FIRST_RUN
    assert notification.fields_for()[FIELD_EVENT] == "first-run"


def test_the_first_run_summary_after_a_reset() -> None:
    planned = Planned(
        MessageKind.FIRST_RUN,
        Severity.NOTICE,
        EventType.FIRST_RUN,
        drives=(DriveMessage(SSD, ()),),
        tool=(
            Item(
                event=EventType.PROBLEM,
                check="tool.state_reset",
                severity=Severity.NOTICE,
                text="the state file was set aside and the tool started afresh: broken",
            ),
        ),
        state_reset="the state file is not valid JSON",
    )

    golden("first-run-reset", render(planned, RenderContext(node="pve1", version="0.4.0")))


def test_a_condition_of_the_tool() -> None:
    planned = Planned(
        MessageKind.TOOL,
        Severity.WARNING,
        EventType.PROBLEM,
        tool=(
            Item(
                event=EventType.PROBLEM,
                check="tool.transport_degraded",
                severity=Severity.WARNING,
                text="the notify bridge is missing at /usr/libexec/pve-smart-alert/notify-bridge;"
                " notifications are sent as mail to root, without their severity",
            ),
        ),
    )

    notification = render(planned, CONTEXT)

    golden("tool", notification)
    assert notification.event is EventType.TOOL
    assert notification.fields[FIELD_EVENT] == "problem"
    assert notification.fields[FIELD_DEVICE] == "pve-smart-alert"


def test_a_drive_message_carries_the_fields_of_the_drive() -> None:
    # FR-502, FR-503.
    fields = render(drive_message(REALLOCATED), CONTEXT).fields_for()

    assert fields == {
        FIELD_TYPE: "pve-smart-alert",
        FIELD_HOSTNAME: "pve1",
        FIELD_EVENT: "problem",
        FIELD_DEVICE: "/dev/sdb",
        FIELD_SERIAL: "ANON-SN-0001",
        FIELD_MODEL: "Samsung SSD 870 EVO 1TB",
    }


def test_the_subject_names_severity_host_drive_and_finding() -> None:
    # FR-508.
    subject = render(drive_message(REALLOCATED), CONTEXT).subject

    assert subject == (
        "[pve-smart-alert] WARNING pve1: /dev/sdb Samsung SSD 870 EVO 1TB (ANON-SN-0001):"
        " 8 reallocated sectors"
    )


def test_the_body_holds_what_fr_507_asks_for() -> None:
    body = render(drive_message(REALLOCATED), CONTEXT).body

    for expected in (
        "pve1 (cluster: lab)",
        "/dev/sdb [sat]",
        "Samsung SSD 870 EVO 1TB",
        "ANON-SN-0001",
        "5000000000000001",
        "SVT02B6Q",
        "1.00 TB, SSD",
        "pci-0000:00:17.0-ata-2",
        'ZFS pool "tank"',
        "ata.reallocated_sectors",
        "WARNING",
        "Reallocated sectors: 8",
        "Thresholds: notice 1, warning 5, critical 70",
    ):
        assert expected in body


def test_the_thresholds_are_the_effective_ones_of_the_drive() -> None:
    from pve_smart_alert.config import CheckOverride

    config = Config(checks={"ata.reallocated_sectors": CheckOverride(warning=3)})

    body = render(drive_message(REALLOCATED), RenderContext(node="pve1", config=config)).body

    assert "Thresholds: notice 1, warning 3, critical 70" in body


def test_the_reminder_named_is_the_configured_one() -> None:
    from datetime import timedelta

    from pve_smart_alert.config import ReminderSettings

    config = Config(notify=NotifySettings(reminder=ReminderSettings(warning=timedelta(days=14))))

    body = render(drive_message(REALLOCATED), RenderContext(node="pve1", config=config)).body

    assert "the next reminder follows in 14 days" in " ".join(body.split())


def test_hostile_strings_of_a_drive_are_cleaned() -> None:
    # ARCHITECTURE.md section 14: drive data is untrusted.
    hostile = DriveInfo(
        key="x",
        name="/dev/sda",
        type="sat",
        model="Evil\nSubject: injected\x1b[31m",
        serial="A" * 500,
        drive_class=DriveClass.HDD,
    )

    notification = render(drive_message(REALLOCATED, drive=hostile), CONTEXT)

    assert "\n" not in notification.subject
    assert "\x1b" not in notification.subject + notification.body
    assert "A" * 201 not in notification.body
    assert "\nSubject: injected" not in notification.body


def test_every_check_and_tool_condition_has_its_texts() -> None:
    assert set(TEXTS) == set(CATALOG) | set(TOOL_CONDITIONS)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("totem {\n  cluster_name: lab\n  config_version: 3\n}\n", "lab"),
        ("logging {\n  debug: off\n}\n", None),
    ],
)
def test_the_cluster_name_is_read_from_corosync(
    tmp_path: Path, content: str, expected: str | None
) -> None:
    path = tmp_path / "corosync.conf"
    path.write_text(content, encoding="utf-8")

    assert cluster_name(path) == expected
    assert cluster_name(tmp_path / "absent.conf") is None
