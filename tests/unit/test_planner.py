# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the notification planner: every rule of ADR 0009 (NFR-15).

The planner is driven as a state machine with an injected clock: each run
plans from the state the last one left, and the changes of a notification
are applied only when the test says it was handed over (FR-517).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from frame import RUN_INTERVAL, Clock

from pve_smart_alert.config import CheckOverride, Config, NotifySettings, ReminderSettings
from pve_smart_alert.model import (
    CheckKind,
    Collection,
    DeviceAccess,
    DriveClass,
    DriveIdentity,
    EventType,
    Finding,
    Location,
    Severity,
    Snapshot,
)
from pve_smart_alert.planner import (
    DRIVE_MISSING,
    DRIVE_UNREADABLE,
    DriveSeen,
    MessageKind,
    Observation,
    Planned,
    Presence,
    SkippedSeen,
    plan,
)
from pve_smart_alert.state import Access, State, identity_key

PENDING = "ata.pending_sectors"
REALLOCATED = "ata.reallocated_sectors"
TEMPERATURE = "temperature"
WEAR = "wear"
CRC = "ata.crc_errors"


def snapshot(
    serial: str | None = "ANON-SN-0001",
    *,
    name: str = "/dev/sda",
    removable: bool | None = False,
    transport: str | None = "sata",
) -> Snapshot:
    return Snapshot(
        identity=DriveIdentity.of("Intenso SSD", serial=serial),
        access=DeviceAccess(name, "sat", "ATA"),
        drive_class=DriveClass.SSD,
        collection=Collection(smartctl_version=(7, 5), exit_status=0),
        location=Location(transport=transport, removable=removable),
    )


def condition(check: str, severity: Severity, value: int | None = None) -> Finding:
    return Finding(check, CheckKind.CONDITION, severity, f"{check} at {value}", value=value)


def event(check: str, value: int) -> Finding:
    return Finding(check, CheckKind.EVENT, Severity.NOTICE, f"{check} rose to {value}", value=value)


def read(drive: Snapshot, *findings: Finding, counters: dict[str, int] | None = None) -> DriveSeen:
    return DriveSeen(
        access=Access(drive.access.name, drive.access.type),
        presence=Presence.READ,
        snapshot=drive,
        findings=findings,
        counters=counters or {},
    )


def unreadable(name: str = "/dev/sda") -> DriveSeen:
    return DriveSeen(Access(name, "sat"), Presence.UNREADABLE, reason="no answer")


@dataclass
class Host:
    """Runs the planner the way the program does, one run after the other."""

    config: Config = field(default_factory=Config)
    state: State = field(default_factory=State)
    clock: Clock = field(default_factory=Clock)

    def run(
        self,
        *drives: DriveSeen,
        delivered: bool = True,
        advance: timedelta = RUN_INTERVAL,
        **observation: object,
    ) -> list[Planned]:
        self.clock.advance(advance)
        result = plan(
            self.state,
            Observation(drives=drives, **observation),  # type: ignore[arg-type]
            self.config,
            now=self.clock(),
            host="pve1",
        )
        if delivered:
            for notification in result.notifications:
                result.apply(notification)
        self.state = result.state
        return list(result.notifications)

    def started(self, *drives: DriveSeen) -> None:
        """Run the first run, whose summary is not the subject of the test."""
        notifications = self.run(*drives)
        assert [notification.kind for notification in notifications] == [MessageKind.FIRST_RUN]

    @property
    def now(self) -> datetime:
        return self.clock()


def events_of(notifications: list[Planned]) -> list[tuple[EventType, str, Severity]]:
    """Return every item of every notification as (event, check, severity)."""
    return [
        (item.event, item.check, item.severity)
        for notification in notifications
        for message in notification.drives
        for item in message.items
    ] + [(item.event, item.check, item.severity) for n in notifications for item in n.tool]


def policy(**settings: object) -> Config:
    return Config(notify=replace(NotifySettings(), **settings))  # type: ignore[arg-type]


DRIVE = snapshot()


# A condition appears (FR-509)


def test_a_new_condition_is_notified_once() -> None:
    host = Host()
    host.started(read(DRIVE))

    first = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))
    second = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    assert events_of(first) == [(EventType.PROBLEM, PENDING, Severity.WARNING)]
    assert first[0].kind is MessageKind.DRIVE
    assert first[0].severity is Severity.WARNING
    assert second == []


def test_the_temperature_needs_two_runs_before_it_is_notified() -> None:
    # FR-308: confirmation count 2 for the temperature, 1 for the others.
    host = Host()
    host.started(read(DRIVE))

    first = host.run(read(DRIVE, condition(TEMPERATURE, Severity.WARNING, 61)))
    second = host.run(read(DRIVE, condition(TEMPERATURE, Severity.WARNING, 62)))

    assert first == []
    assert events_of(second) == [(EventType.PROBLEM, TEMPERATURE, Severity.WARNING)]


def test_a_temperature_seen_once_is_forgotten() -> None:
    host = Host()
    host.started(read(DRIVE))

    host.run(read(DRIVE, condition(TEMPERATURE, Severity.WARNING, 61)))
    host.run(read(DRIVE))
    again = host.run(read(DRIVE, condition(TEMPERATURE, Severity.WARNING, 61)))

    assert again == []
    record = host.state.drives[identity_key(DRIVE.identity)]
    assert record.pending[TEMPERATURE].seen_runs == 1


def test_the_confirmation_count_comes_from_the_configuration() -> None:
    config = Config(checks={PENDING: CheckOverride(confirm_runs=3)})
    host = Host(config=config)
    host.started(read(DRIVE))

    runs = [host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3))) for _ in range(3)]

    assert [events_of(notifications) for notifications in runs] == [
        [],
        [],
        [(EventType.PROBLEM, PENDING, Severity.WARNING)],
    ]


# Severity rises (FR-511)


def test_a_rise_in_severity_is_notified_at_once() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    # Well within the worsening cool-down of six hours.
    escalated = host.run(read(DRIVE, condition(PENDING, Severity.CRITICAL, 20)))

    assert events_of(escalated) == [(EventType.ESCALATED, PENDING, Severity.CRITICAL)]
    item = escalated[0].drives[0].items[0]
    assert (item.previous, item.value) == (3, 20)
    assert escalated[0].event is EventType.ESCALATED


# Value worsens at the same severity (FR-512)


def test_a_worse_value_waits_for_the_cool_down_of_the_drive() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    soon = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 5)))
    later = host.run(
        read(DRIVE, condition(PENDING, Severity.WARNING, 6)), advance=timedelta(hours=6)
    )
    unchanged = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 6)))

    assert soon == []
    assert events_of(later) == [(EventType.WORSENED, PENDING, Severity.WARNING)]
    item = later[0].drives[0].items[0]
    assert (item.previous, item.value) == (3, 6)
    assert unchanged == []


def test_a_gauge_does_not_worsen_below_the_next_severity() -> None:
    # "Worsens" is escalation only for gauges such as temperature and wear.
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(WEAR, Severity.NOTICE, 80)))

    later = host.run(read(DRIVE, condition(WEAR, Severity.NOTICE, 90)), advance=timedelta(days=1))

    assert later == []


def test_the_cool_down_counts_from_any_notification_about_the_drive() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))
    host.run(
        read(
            DRIVE,
            condition(PENDING, Severity.WARNING, 3),
            condition(REALLOCATED, Severity.WARNING, 5),
        ),
        advance=timedelta(hours=5),
    )

    # Six hours after the first notification, but one after the second.
    worse = host.run(
        read(
            DRIVE,
            condition(PENDING, Severity.WARNING, 4),
            condition(REALLOCATED, Severity.WARNING, 5),
        ),
        advance=timedelta(hours=1),
    )

    assert worse == []


# Nothing changed and the reminder interval has passed (FR-510)


def test_a_warning_is_reminded_after_seven_days() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    early = host.run(
        read(DRIVE, condition(PENDING, Severity.WARNING, 3)), advance=timedelta(days=6, hours=23)
    )
    due = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)), advance=timedelta(hours=1))
    after = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    assert early == []
    assert events_of(due) == [(EventType.REMINDER, PENDING, Severity.WARNING)]
    assert after == []


def test_a_critical_condition_is_reminded_after_three_days() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.CRITICAL, 20)))

    due = host.run(
        read(DRIVE, condition(PENDING, Severity.CRITICAL, 20)), advance=timedelta(days=3)
    )

    assert events_of(due) == [(EventType.REMINDER, PENDING, Severity.CRITICAL)]


def test_a_notice_is_never_reminded() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(WEAR, Severity.NOTICE, 81)))

    later = host.run(read(DRIVE, condition(WEAR, Severity.NOTICE, 81)), advance=timedelta(days=400))

    assert later == []


def test_the_reminder_intervals_come_from_the_configuration() -> None:
    host = Host(config=policy(reminder=ReminderSettings(warning=timedelta(days=1), notice=None)))
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    due = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)), advance=timedelta(days=1))

    assert events_of(due) == [(EventType.REMINDER, PENDING, Severity.WARNING)]


# Severity falls


def test_a_falling_severity_is_not_notified_and_counts_from_then_on() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.CRITICAL, 20)))

    fallen = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 10)))
    risen = host.run(read(DRIVE, condition(PENDING, Severity.CRITICAL, 18)))

    assert fallen == []
    # The lower severity was used from then on, so the rise is an escalation.
    assert events_of(risen) == [(EventType.ESCALATED, PENDING, Severity.CRITICAL)]


# The condition clears (FR-513)


def test_a_condition_absent_for_two_runs_recovers_once() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    first = host.run(read(DRIVE))
    second = host.run(read(DRIVE))
    third = host.run(read(DRIVE))

    assert first == []
    assert events_of(second) == [(EventType.RECOVERED, PENDING, Severity.WARNING)]
    assert second[0].severity is Severity.INFO
    assert second[0].event is EventType.RECOVERED
    assert third == []
    assert host.state.drives[identity_key(DRIVE.identity)].conditions == {}


def test_a_value_that_flips_does_not_notify_again() -> None:
    # The flapping temperature of ADR 0009: absent for one run is not enough.
    host = Host()
    host.started(read(DRIVE))
    hot = condition(TEMPERATURE, Severity.WARNING, 61)
    host.run(read(DRIVE, hot))
    host.run(read(DRIVE, hot))

    flips = [host.run(read(DRIVE, *((hot,) if run % 2 else ()))) for run in range(8)]

    assert all(notifications == [] for notifications in flips)


def test_recoveries_can_be_switched_off() -> None:
    host = Host(config=policy(recovery=False))
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    runs = [host.run(read(DRIVE)) for _ in range(3)]

    assert runs == [[], [], []]
    assert host.state.drives[identity_key(DRIVE.identity)].conditions == {}


def test_the_clear_count_comes_from_the_configuration() -> None:
    host = Host(config=policy(clear_runs=3))
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    runs = [events_of(host.run(read(DRIVE))) for _ in range(3)]

    assert runs == [[], [], [(EventType.RECOVERED, PENDING, Severity.WARNING)]]


def test_a_check_switched_off_drops_its_condition_silently() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))
    host.config = Config(checks={PENDING: CheckOverride(enabled=False)})

    runs = [host.run(read(DRIVE)) for _ in range(3)]

    assert runs == [[], [], []]


# Events (FR-306)


def test_an_old_counter_value_never_alerts() -> None:
    host = Host()
    host.started(read(DRIVE, counters={CRC: 12}))

    assert host.state.drives[identity_key(DRIVE.identity)].baselines == {CRC: 12}
    assert host.run(read(DRIVE, counters={CRC: 12})) == []


def test_a_rising_counter_is_notified_and_its_baseline_moves() -> None:
    host = Host()
    host.started(read(DRIVE, counters={CRC: 12}))

    rose = host.run(read(DRIVE, event(CRC, 19), counters={CRC: 19}))

    assert events_of(rose) == [(EventType.PROBLEM, CRC, Severity.NOTICE)]
    item = rose[0].drives[0].items[0]
    assert (item.previous, item.value) == (12, 19)
    assert host.state.drives[identity_key(DRIVE.identity)].baselines == {CRC: 19}


def test_a_counter_that_keeps_rising_waits_for_the_event_cool_down() -> None:
    host = Host()
    host.started(read(DRIVE, counters={CRC: 12}))
    host.run(read(DRIVE, event(CRC, 19), counters={CRC: 19}))

    soon = host.run(read(DRIVE, event(CRC, 25), counters={CRC: 25}))
    later = host.run(read(DRIVE, event(CRC, 30), counters={CRC: 30}), advance=timedelta(hours=24))

    assert soon == []
    # The baseline stayed at 19 meanwhile, so the whole rise is reported.
    assert later[0].drives[0].items[0].previous == 19
    assert host.state.drives[identity_key(DRIVE.identity)].baselines == {CRC: 30}


def test_a_counter_below_its_baseline_lowers_it_silently() -> None:
    host = Host()
    host.started(read(DRIVE, counters={CRC: 12}))

    reset = host.run(read(DRIVE, counters={CRC: 0}))

    assert reset == []
    assert host.state.drives[identity_key(DRIVE.identity)].baselines == {CRC: 0}


def test_an_event_has_no_recovery_and_no_reminder() -> None:
    host = Host()
    host.started(read(DRIVE, counters={CRC: 12}))
    host.run(read(DRIVE, event(CRC, 19), counters={CRC: 19}))

    later = [host.run(read(DRIVE, counters={CRC: 19}), advance=timedelta(days=8)) for _ in range(3)]

    assert later == [[], [], []]


def test_a_drive_that_appears_later_starts_its_counters_from_their_values() -> None:
    host = Host()
    host.started(read(DRIVE))
    other = snapshot("ANON-SN-0002", name="/dev/sdb")

    appeared = host.run(read(DRIVE), read(other, counters={CRC: 40}))

    assert appeared == []
    assert host.state.drives[identity_key(other.identity)].baselines == {CRC: 40}


def test_a_drive_that_appears_later_reports_its_conditions_in_a_drive_message() -> None:
    # Not a first run (ADR 0009): its conditions are reported once, normally.
    host = Host()
    host.started(read(DRIVE))
    other = snapshot("ANON-SN-0002", name="/dev/sdb")

    appeared = host.run(read(DRIVE), read(other, condition(REALLOCATED, Severity.NOTICE, 2)))

    assert [notification.kind for notification in appeared] == [MessageKind.DRIVE]
    assert events_of(appeared) == [(EventType.PROBLEM, REALLOCATED, Severity.NOTICE)]


# Drives that disappear (FR-309)


def test_a_drive_absent_for_two_runs_is_notified_once() -> None:
    host = Host()
    host.started(read(DRIVE))

    runs = [host.run() for _ in range(4)]

    assert runs[0] == []
    assert events_of(runs[1]) == [(EventType.MISSING, DRIVE_MISSING, Severity.WARNING)]
    assert runs[1][0].drives[0].drive.present is False
    assert runs[1][0].drives[0].drive.serial == "ANON-SN-0001"
    assert runs[2:] == [[], []]


def test_a_returning_drive_is_not_announced() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run()
    host.run()

    returned = host.run(read(DRIVE))
    gone_again = [host.run(), host.run()]

    assert returned == []
    # Gone again later is a new absence and is notified again.
    assert events_of(gone_again[1]) == [(EventType.MISSING, DRIVE_MISSING, Severity.WARNING)]


def test_removable_usb_and_unstable_drives_are_exempt() -> None:
    drives = [
        snapshot("ANON-SN-0002", name="/dev/sdb", removable=True),
        snapshot("ANON-SN-0003", name="/dev/sdc", transport="usb"),
        snapshot(None, name="/dev/sdd"),
    ]
    host = Host()
    host.started(*(read(drive) for drive in drives))

    runs = [host.run() for _ in range(3)]

    assert runs == [[], [], []]


def test_the_conditions_of_a_missing_drive_are_frozen() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    # Gone for longer than the reminder interval and the clear count.
    gone = [host.run(advance=timedelta(days=4)) for _ in range(3)]

    assert events_of(gone[1]) == [(EventType.MISSING, DRIVE_MISSING, Severity.WARNING)]
    assert gone[0] == gone[2] == []
    record = host.state.drives[identity_key(DRIVE.identity)]
    assert set(record.conditions) == {PENDING}


def test_a_failed_scan_does_not_count_drives_as_missing() -> None:
    host = Host()
    host.started(read(DRIVE))

    runs = [host.run(presence_known=False) for _ in range(3)]

    assert runs == [[], [], []]


def test_a_record_not_seen_for_ninety_days_is_removed() -> None:
    # ADR 0007: retention.
    host = Host()
    host.started(read(DRIVE))

    host.run(advance=timedelta(days=91))

    assert host.state.drives == {}


def test_a_drive_that_is_excluded_now_is_forgotten() -> None:
    host = Host()
    host.started(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    excluded = host.run(
        skipped=(SkippedSeen(Access("/dev/sda", "sat"), "excluded", identity=DRIVE.identity),)
    )

    assert excluded == []
    assert host.state.drives == {}
    assert host.state.skipped["/dev/sda|sat"].reason == "excluded"


# Drives that stop answering (FR-310)


def test_a_drive_without_usable_data_for_two_runs_is_unreadable() -> None:
    host = Host()
    host.started(read(DRIVE))

    first = host.run(unreadable())
    second = host.run(unreadable())
    third = host.run(unreadable())

    assert first == []
    assert events_of(second) == [(EventType.PROBLEM, DRIVE_UNREADABLE, Severity.WARNING)]
    assert second[0].drives[0].drive.serial == "ANON-SN-0001"
    assert third == []


def test_an_unreadable_drive_that_answers_again_recovers() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(unreadable())
    host.run(unreadable())

    runs = [events_of(host.run(read(DRIVE))) for _ in range(2)]

    assert runs == [[], [(EventType.RECOVERED, DRIVE_UNREADABLE, Severity.WARNING)]]


def test_the_conditions_of_an_unreadable_drive_are_frozen() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    runs = [host.run(unreadable(), advance=timedelta(days=4)) for _ in range(3)]

    assert [events_of(notifications) for notifications in runs] == [
        [],
        [(EventType.PROBLEM, DRIVE_UNREADABLE, Severity.WARNING)],
        [],
    ]
    record = host.state.drives[identity_key(DRIVE.identity)]
    assert set(record.conditions) == {PENDING, DRIVE_UNREADABLE}
    # The frozen condition is shown with the message, for context.
    assert [item.check for item in runs[1][0].drives[0].active] == [PENDING]


def test_a_device_that_never_answered_is_unreadable_by_its_path() -> None:
    host = Host()
    host.started(read(DRIVE))

    runs = [host.run(read(DRIVE), unreadable("/dev/sdz")) for _ in range(2)]
    gone = [host.run(read(DRIVE)) for _ in range(2)]

    assert events_of(runs[1]) == [(EventType.PROBLEM, DRIVE_UNREADABLE, Severity.WARNING)]
    assert runs[1][0].drives[0].drive.name == "/dev/sdz"
    assert events_of(gone[1]) == [(EventType.RECOVERED, DRIVE_UNREADABLE, Severity.WARNING)]
    assert set(host.state.drives) == {identity_key(DRIVE.identity)}


def test_a_drive_in_standby_keeps_its_state() -> None:
    # FR-203: skipped for the run, its previous state is kept.
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    runs = [
        host.run(DriveSeen(Access("/dev/sda", "sat"), Presence.STANDBY), advance=timedelta(days=8))
        for _ in range(3)
    ]

    assert runs == [[], [], []]
    record = host.state.drives[identity_key(DRIVE.identity)]
    assert set(record.conditions) == {PENDING}
    assert record.missing_runs == 0


# Grouping (FR-514, FR-515, NFR-10)


def test_the_notifications_of_one_drive_are_one_message() -> None:
    host = Host()
    host.started(read(DRIVE))

    due = host.run(
        read(
            DRIVE,
            condition(PENDING, Severity.WARNING, 3),
            condition(REALLOCATED, Severity.CRITICAL, 80),
        )
    )

    assert len(due) == 1
    assert due[0].severity is Severity.CRITICAL
    assert {item.check for item in due[0].drives[0].items} == {PENDING, REALLOCATED}


def test_more_drives_than_the_limit_are_one_summary() -> None:
    drives = [
        snapshot(f"ANON-SN-000{number}", name=f"/dev/sd{letter}")
        for number, letter in zip(range(1, 6), "abcde", strict=True)
    ]
    host = Host()
    host.started(*(read(drive) for drive in drives))

    due = host.run(*(read(drive, condition(PENDING, Severity.WARNING, 3)) for drive in drives))

    assert [notification.kind for notification in due] == [MessageKind.SUMMARY]
    assert len(due[0].drives) == 5
    assert due[0].event is EventType.SUMMARY
    # The summary carries the changes of all five: nothing is due afterwards.
    assert (
        host.run(*(read(drive, condition(PENDING, Severity.WARNING, 3)) for drive in drives)) == []
    )


def test_up_to_the_limit_each_drive_has_its_own_message() -> None:
    drives = [
        snapshot(f"ANON-SN-000{number}", name=f"/dev/sd{letter}")
        for number, letter in zip(range(1, 4), "abc", strict=True)
    ]
    host = Host()
    host.started(*(read(drive) for drive in drives))

    due = host.run(*(read(drive, condition(PENDING, Severity.WARNING, 3)) for drive in drives))

    assert [notification.kind for notification in due] == [MessageKind.DRIVE] * 3


def test_the_grouping_limit_comes_from_the_configuration() -> None:
    drives = [
        snapshot(f"ANON-SN-000{number}", name=f"/dev/sd{letter}")
        for number, letter in zip(range(1, 3), "ab", strict=True)
    ]
    host = Host(config=policy(max_drive_notifications=1))
    host.started(*(read(drive) for drive in drives))

    due = host.run(*(read(drive, condition(PENDING, Severity.WARNING, 3)) for drive in drives))

    assert [notification.kind for notification in due] == [MessageKind.SUMMARY]


def test_the_tool_has_its_own_message_besides_the_drives() -> None:
    # NFR-10: the drive limit, plus at most one message about the tool.
    drives = [
        snapshot(f"ANON-SN-000{number}", name=f"/dev/sd{letter}")
        for number, letter in zip(range(1, 6), "abcde", strict=True)
    ]
    host = Host()
    host.started(*(read(drive) for drive in drives))
    tool = Finding("tool.scan_failed", CheckKind.CONDITION, Severity.WARNING, "scan failed")

    due = host.run(
        *(read(drive, condition(PENDING, Severity.WARNING, 3)) for drive in drives), tool=(tool,)
    )

    assert [notification.kind for notification in due] == [MessageKind.SUMMARY, MessageKind.TOOL]


# The first run (FR-516)


def test_the_first_run_sends_exactly_one_summary() -> None:
    other = snapshot("ANON-SN-0002", name="/dev/sdb")
    host = Host()

    first = host.run(
        read(DRIVE, condition(PENDING, Severity.WARNING, 3), counters={CRC: 7}),
        read(other),
        unreadable("/dev/sdz"),
        skipped=(SkippedSeen(Access("/dev/sdy", "scsi"), "not-a-disk"),),
    )

    assert len(first) == 1
    summary = first[0]
    assert summary.kind is MessageKind.FIRST_RUN
    assert summary.event is EventType.FIRST_RUN
    assert summary.severity is Severity.WARNING
    assert [message.drive.name for message in summary.drives] == ["/dev/sda", "/dev/sdb"]
    assert [item.check for item in summary.drives[0].items] == [PENDING]
    assert [seen.access.name for seen in summary.unreadable] == ["/dev/sdz"]
    assert [skipped.reason for skipped in summary.skipped] == ["not-a-disk"]
    # Everything is recorded as already notified, with the baselines.
    record = host.state.drives[identity_key(DRIVE.identity)]
    assert record.conditions[PENDING].last_notified == host.now
    assert record.baselines == {CRC: 7}
    assert host.state.initialized == host.now
    assert (
        host.run(
            read(DRIVE, condition(PENDING, Severity.WARNING, 3), counters={CRC: 7}), read(other)
        )
        == []
    )


def test_the_first_run_without_findings_is_info() -> None:
    host = Host()

    first = host.run(read(DRIVE))

    assert first[0].severity is Severity.INFO


def test_the_first_run_records_temperatures_without_waiting() -> None:
    host = Host()
    hot = condition(TEMPERATURE, Severity.WARNING, 61)
    host.run(read(DRIVE, hot))

    assert host.run(read(DRIVE, hot)) == []


def test_the_first_run_summary_can_be_switched_off() -> None:
    host = Host(config=policy(first_run_summary=False))

    first = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))

    assert first == []
    assert host.state.initialized is not None
    assert host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3))) == []


def test_a_reset_state_is_mentioned_in_the_summary() -> None:
    # NFR-12: the following notification is a single summary.
    host = Host()

    first = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)), state_reset="broken")

    assert len(first) == 1
    assert first[0].kind is MessageKind.FIRST_RUN
    assert first[0].state_reset == "broken"
    assert [item.check for item in first[0].tool] == ["tool.state_reset"]


# Delivery and state (FR-517)


def test_a_notification_that_was_not_handed_over_is_planned_again() -> None:
    host = Host()
    host.started(read(DRIVE))

    failed = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)), delivered=False)
    retried = host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 4)))

    assert events_of(failed) == [(EventType.PROBLEM, PENDING, Severity.WARNING)]
    # The retry describes the situation when it is finally sent.
    assert events_of(retried) == [(EventType.PROBLEM, PENDING, Severity.WARNING)]
    assert retried[0].drives[0].items[0].value == 4


def test_a_first_run_whose_summary_failed_is_a_first_run_again() -> None:
    host = Host()

    host.run(read(DRIVE), delivered=False)
    again = host.run(read(DRIVE))

    assert [notification.kind for notification in again] == [MessageKind.FIRST_RUN]


def test_a_recovery_that_failed_is_sent_on_the_next_run() -> None:
    host = Host()
    host.started(read(DRIVE))
    host.run(read(DRIVE, condition(PENDING, Severity.WARNING, 3)))
    host.run(read(DRIVE))

    failed = host.run(read(DRIVE), delivered=False)
    retried = host.run(read(DRIVE))

    assert events_of(failed) == events_of(retried)


def test_an_event_that_failed_keeps_its_baseline() -> None:
    host = Host()
    host.started(read(DRIVE, counters={CRC: 12}))

    host.run(read(DRIVE, event(CRC, 19), counters={CRC: 19}), delivered=False)

    assert host.state.drives[identity_key(DRIVE.identity)].baselines == {CRC: 12}


# Problems of the tool itself (FR-518)


def test_a_condition_of_the_tool_follows_the_same_rules() -> None:
    host = Host()
    host.started(read(DRIVE))
    scan = Finding("tool.scan_failed", CheckKind.CONDITION, Severity.WARNING, "scan failed")

    appeared = host.run(read(DRIVE), tool=(scan,))
    unchanged = host.run(read(DRIVE), tool=(scan,))
    reminded = host.run(read(DRIVE), tool=(scan,), advance=timedelta(days=7))
    cleared = [host.run(read(DRIVE)) for _ in range(2)]

    assert [notification.kind for notification in appeared] == [MessageKind.TOOL]
    assert events_of(appeared) == [(EventType.PROBLEM, "tool.scan_failed", Severity.WARNING)]
    assert unchanged == []
    assert events_of(reminded) == [(EventType.REMINDER, "tool.scan_failed", Severity.WARNING)]
    assert cleared[0] == []
    assert events_of(cleared[1]) == [(EventType.RECOVERED, "tool.scan_failed", Severity.WARNING)]


def test_the_planner_leaves_the_state_it_was_given_alone() -> None:
    state = State()

    plan(state, Observation(drives=(read(DRIVE),)), Config(), now=Clock()(), host="pve1")

    assert state == State()
