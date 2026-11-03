# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the renderer: subject and body against golden files (ADR 0016).

A golden file holds the subject, the metadata fields that matchers and
webhooks see, one `Field NAME: VALUE` line each in the order of their
names, and the body. A change to the text or the fields of a notification
has to update its golden file in `tests/fixtures/golden/`. With
PVE_SMART_ALERT_UPDATE_GOLDEN=1 the tests write the files instead of
comparing them; the diff is then reviewed like any other change.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pve_smart_alert.checks import CATALOG
from pve_smart_alert.config import Config, NotifySettings
from pve_smart_alert.model import (
    FIELD_DEVICE,
    FIELD_DEVICE_ID,
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
from pve_smart_alert.render import (
    TEXTS,
    RenderContext,
    cluster_name,
    render,
    render_test_notification,
)
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

# A SAS drive read as `megaraid,8` on SCSI host 6 (ADR 0028).
BEHIND_CONTROLLER = DriveInfo(
    key="SEAGATE ST600MP0036|ANON-SN-0002",
    name="/dev/bus/6",
    type="megaraid,8",
    model="SEAGATE ST600MP0036",
    serial="ANON-SN-0002",
    wwn="5000c50000000002",
    firmware="KT3A",
    capacity_bytes=600_127_266_816,
    drive_class=DriveClass.HDD,
    location="/dev/bus/6 (megaraid_sas), device 8",
    power_on_hours=4665,
)

GROWN_DEFECTS = Item(
    event=EventType.PROBLEM,
    check="scsi.grown_defects",
    severity=Severity.WARNING,
    text="150 defects, at or above the warning threshold of 100",
    value=150,
    threshold=100,
    since=SINCE,
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
    """Compare subject, fields and body with a golden file, or write it."""
    fields = "".join(
        f"Field {name}: {value}\n" for name, value in sorted(notification.fields_for().items())
    )
    text = f"Subject: {notification.subject}\n{fields}\n{notification.body}"
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


def test_a_drive_behind_a_raid_controller_names_controller_and_device_id() -> None:
    # FR-507, ADR 0028: a SAS drive read as `megaraid,8` on SCSI host 6.
    notification = render(drive_message(GROWN_DEFECTS, drive=BEHIND_CONTROLLER), CONTEXT)

    golden("drive-problem-megaraid", notification)
    assert "Location:   /dev/bus/6 (megaraid_sas), device 8\n" in notification.body
    # The device ID tells it apart from the other drives behind the
    # controller, which share `device` (FR-503, ADR 0029).
    fields = notification.fields_for()
    assert fields[FIELD_DEVICE] == "/dev/bus/6"
    assert fields[FIELD_DEVICE_ID] == "8"


@pytest.mark.parametrize(
    ("device_type", "device_id"),
    [
        ("megaraid,8", "8"),
        ("sat+megaraid,14", "14"),
        ("megaraid,0", "0"),
        # The drives behind an HPE Smart Array controller (ADR 0032).
        ("cciss,0", "0"),
        ("cciss,3", "3"),
    ],
)
def test_the_device_id_is_the_one_of_the_pass_through_type(
    device_type: str, device_id: str
) -> None:
    drive = replace(BEHIND_CONTROLLER, type=device_type)

    fields = render(drive_message(GROWN_DEFECTS, drive=drive), CONTEXT).fields_for()

    assert fields[FIELD_DEVICE_ID] == device_id


@pytest.mark.parametrize("device_type", ["sat", "nvme", "scsi", "auto", "ata", "megaraid", "cciss"])
def test_a_drive_read_directly_carries_no_device_id(device_type: str) -> None:
    drive = replace(SSD, type=device_type)

    fields = render(drive_message(REALLOCATED, drive=drive), CONTEXT).fields_for()

    assert FIELD_DEVICE_ID not in fields


def test_the_wwn_of_the_template_data_carries_no_control_character() -> None:
    # `data` is handed to templates an administrator can override; every
    # other string in it is cleaned (ARCHITECTURE.md section 14). The state
    # keeps a WWN as it was written, and not every writer validates it.
    drive = replace(SSD, wwn="5000000000000001\x1b[2J")

    notification = render(drive_message(REALLOCATED, drive=drive), CONTEXT)

    drives = notification.data["drives"]
    assert isinstance(drives, list)
    (drive_data,) = drives
    assert isinstance(drive_data, dict)
    assert "\x1b" not in drive_data["wwn"]


def test_a_drive_behind_an_hpe_controller_names_controller_and_device_id() -> None:
    # FR-507, ADR 0032: a drive read as `cciss,0` on the controller's node.
    drive = replace(
        BEHIND_CONTROLLER,
        name="/dev/sg1",
        type="cciss,0",
        location="/dev/sg1 (hpsa), device 0",
    )

    notification = render(drive_message(GROWN_DEFECTS, drive=drive), CONTEXT)

    assert "Location:   /dev/sg1 (hpsa), device 0\n" in notification.body
    fields = notification.fields_for()
    assert fields[FIELD_DEVICE] == "/dev/sg1"
    assert fields[FIELD_DEVICE_ID] == "0"


def test_a_missing_drive_behind_a_raid_controller_keeps_its_last_device_id() -> None:
    # A missing drive is shown with what the state knows: the type of the
    # last read gives the device ID (ADR 0029).
    gone = replace(
        BEHIND_CONTROLLER, type="megaraid,9", present=False, last_seen=SINCE, power_on_hours=None
    )
    missing = Item(
        event=EventType.MISSING,
        check="drive.missing",
        severity=Severity.WARNING,
        text="the drive was not found in 2 runs in a row; last seen 2026-10-03T12:34:12Z as"
        " /dev/bus/6",
        value=2,
        since=SINCE,
    )

    fields = render(drive_message(missing, drive=gone), CONTEXT).fields_for()

    assert fields[FIELD_EVENT] == "missing"
    assert fields[FIELD_DEVICE] == "/dev/bus/6"
    assert fields[FIELD_DEVICE_ID] == "9"


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


def test_a_summary_of_drives_behind_a_controller_carries_no_device_id() -> None:
    # Not about one drive, so neither `device` nor `device-id` (ADR 0029).
    planned = Planned(
        MessageKind.SUMMARY,
        Severity.WARNING,
        EventType.SUMMARY,
        drives=tuple(
            DriveMessage(replace(BEHIND_CONTROLLER, type=f"megaraid,{number}"), (GROWN_DEFECTS,))
            for number in range(4)
        ),
    )

    fields = render(planned, CONTEXT).fields_for()

    assert set(fields) == {FIELD_TYPE, FIELD_HOSTNAME, FIELD_EVENT}


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


def test_the_first_run_summary_carries_no_device_id() -> None:
    planned = Planned(
        MessageKind.FIRST_RUN,
        Severity.WARNING,
        EventType.FIRST_RUN,
        drives=(DriveMessage(BEHIND_CONTROLLER, (GROWN_DEFECTS,)),),
    )

    fields = render(planned, CONTEXT).fields_for()

    assert set(fields) == {FIELD_TYPE, FIELD_HOSTNAME, FIELD_EVENT}


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
    assert FIELD_DEVICE_ID not in notification.fields_for()


@pytest.mark.parametrize("severity", list(Severity))
def test_the_test_notification_carries_no_device_id(severity: Severity) -> None:
    fields = render_test_notification(severity, node="pve1").fields_for()

    assert set(fields) == {FIELD_TYPE, FIELD_HOSTNAME, FIELD_EVENT}


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
