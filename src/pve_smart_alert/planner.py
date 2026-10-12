# SPDX-License-Identifier: AGPL-3.0-or-later
"""The notification planner: which notifications are due, and what they change (ADR 0009).

The planner is a pure function (ARCHITECTURE.md section 7): it takes the
state of the last run, what this run observed, the configuration and the
current time, and returns the state with every change that needs no
notification, together with the notifications that are due. Each
notification carries the changes that may be stored only once it has been
handed over (ADR 0007, FR-517); a notification that fails leaves them out,
and the next run plans it again from fresh data. Time is passed in and never
read here, which is what makes every rule testable.

The rules, in short (ADR 0009):

- A condition is notified once when it appears, after its confirmation
  count (`problem`); again at once when its severity rises (`escalated`);
  when its value worsens at the same severity, for checks that track
  worsening, after the cool-down of the drive (`worsened`); and after the
  reminder interval of its severity (`reminder`). A falling severity is not
  notified. A condition absent for the clear count is notified as
  `recovered`, with severity info.
- An event, the rise of a cumulative counter above its baseline, is notified
  after the event cool-down of its drive and check, and its baseline moves
  then. A counter below its baseline lowers it silently.
- A drive absent for the missing count is notified once (`missing`); a drive
  without usable data for the unreadable count gets the condition
  `drive.unreadable`. Meanwhile its other conditions are frozen.
- All notifications of one drive in one run are one message; more drives
  than the grouping limit are one summary. The tool has its own message.
- The first run records everything as notified and sends one summary.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from pve_smart_alert.checks import CATALOG, Worsening
from pve_smart_alert.config import Config, NotifySettings, effective_check, effective_checks
from pve_smart_alert.model import (
    CheckKind,
    DriveClass,
    DriveIdentity,
    EventType,
    Finding,
    Severity,
    Snapshot,
)
from pve_smart_alert.state import (
    RETENTION,
    Access,
    ConditionRecord,
    DriveDetails,
    DriveRecord,
    PendingRecord,
    SkippedRecord,
    State,
    ToolRecord,
    format_time,
    identity_key,
)
from pve_smart_alert.tool_conditions import TOOL_CONDITIONS

__all__ = [
    "DRIVE_MISSING",
    "DRIVE_UNREADABLE",
    "RANK",
    "Change",
    "DriveInfo",
    "DriveMessage",
    "DriveSeen",
    "Item",
    "MessageKind",
    "Observation",
    "Plan",
    "Planned",
    "Presence",
    "SkippedSeen",
    "plan",
]

#: The checks the planner raises itself, from presence and not from a snapshot.
DRIVE_MISSING: Final = "drive.missing"
DRIVE_UNREADABLE: Final = "drive.unreadable"

#: The order of the severities. Info carries recoveries and the summaries
#: without findings (ADR 0008).
RANK: Final[Mapping[Severity, int]] = {
    Severity.INFO: 0,
    Severity.NOTICE: 1,
    Severity.WARNING: 2,
    Severity.CRITICAL: 3,
}

# Which event names a message about one drive, when it carries several.
_EVENT_ORDER: Final = (
    EventType.ESCALATED,
    EventType.PROBLEM,
    EventType.WORSENED,
    EventType.MISSING,
    EventType.REMINDER,
    EventType.RECOVERED,
)

# A state change that belongs to a notification, applied once it was handed over.
Change = Callable[[State], None]

# Why a skipped device takes a known drive out of monitoring.
_UNMONITORED: Final = frozenset({"excluded", "no-smart"})


class Presence(StrEnum):
    """How a device answered in this run."""

    READ = "read"
    # Asleep and not woken; it keeps its previous state (FR-203).
    STANDBY = "standby"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class DriveSeen:
    """One device of this run, as the planner needs it.

    `findings` are the conditions and the events of a drive that was read;
    an event finding is there only when its counter is above the baseline the
    planner handed to the evaluation. `counters` holds the current value of
    every event counter that is enabled for the drive, so that the planner
    can record and lower baselines. `reason` says why a device is unreadable.
    """

    access: Access
    presence: Presence
    snapshot: Snapshot | None = None
    findings: tuple[Finding, ...] = ()
    counters: Mapping[str, int] = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True)
class SkippedSeen:
    """A device that discovery skipped, with the identity it answered with, if any."""

    access: Access
    reason: str
    detail: str | None = None
    identity: DriveIdentity | None = None


@dataclass(frozen=True)
class Observation:
    """What one run saw (ARCHITECTURE.md section 3, steps 4 to 8).

    `tool` are the conditions of the tool that hold now. `state_reset` says
    why the state was set aside, when it was. When the device scan failed,
    `presence_known` is false: drives that were not found were not looked
    for, so their absence is not counted.
    """

    drives: tuple[DriveSeen, ...] = ()
    skipped: tuple[SkippedSeen, ...] = ()
    tool: tuple[Finding, ...] = ()
    state_reset: str | None = None
    presence_known: bool = True


@dataclass(frozen=True)
class Item:
    """One reason inside a notification: one check of one drive or of the tool.

    `previous` is the value at the last notification, or the baseline of an
    event (ADR 0009: each notification states the previous and the current
    value). For `recovered`, `severity` is the severity the condition had.
    """

    event: EventType
    check: str
    severity: Severity
    text: str
    value: int | None = None
    previous: int | None = None
    threshold: int | None = None
    since: datetime | None = None
    previous_severity: Severity | None = None

    @property
    def message_severity(self) -> Severity:
        """The severity this item gives its message: a recovery is info."""
        return Severity.INFO if self.event is EventType.RECOVERED else self.severity


@dataclass(frozen=True)
class DriveInfo:
    """What a message shows about a drive, from this run or from the state.

    `present` is false for a drive that is missing or unreadable now; its
    details then come from the last run that read it.
    """

    key: str
    name: str
    type: str
    model: str | None = None
    serial: str | None = None
    wwn: str | None = None
    firmware: str | None = None
    capacity_bytes: int | None = None
    drive_class: DriveClass | None = None
    location: str | None = None
    used_by: str | None = None
    power_on_hours: int | None = None
    present: bool = True
    last_seen: datetime | None = None


@dataclass(frozen=True)
class DriveMessage:
    """What one message says about one drive.

    `items` are due now. `active` are the other conditions of the drive that
    are still active, for context; they cause nothing by themselves.
    """

    drive: DriveInfo
    items: tuple[Item, ...]
    active: tuple[Item, ...] = ()

    @property
    def severity(self) -> Severity:
        return max((item.message_severity for item in self.items), key=RANK.__getitem__)

    @property
    def event(self) -> EventType:
        events = {item.event for item in self.items}
        return next(event for event in _EVENT_ORDER if event in events)


class MessageKind(StrEnum):
    """What a planned notification is about."""

    DRIVE = "drive"
    SUMMARY = "summary"
    FIRST_RUN = "first-run"
    TOOL = "tool"


@dataclass(frozen=True)
class Planned:
    """One notification that is due, before it is rendered.

    `drives` holds one drive for `drive`, the affected drives for `summary`,
    and every monitored drive for `first-run`. `tool` are the items of the
    tool. `skipped` and `unreadable` are listed by the first-run summary.
    `changes` are stored only after the notification was handed over.
    """

    kind: MessageKind
    severity: Severity
    event: EventType
    drives: tuple[DriveMessage, ...] = ()
    tool: tuple[Item, ...] = ()
    tool_active: tuple[Item, ...] = ()
    skipped: tuple[SkippedSeen, ...] = ()
    unreadable: tuple[DriveSeen, ...] = ()
    state_reset: str | None = None
    changes: tuple[Change, ...] = ()


@dataclass(frozen=True)
class Plan:
    """The state with the changes that need no notification, and what is due."""

    state: State
    notifications: tuple[Planned, ...]

    def apply(self, notification: Planned) -> None:
        """Store the changes of a notification that was handed over."""
        for change in notification.changes:
            change(self.state)


def plan(
    state: State,
    observation: Observation,
    config: Config,
    *,
    now: datetime,
    host: str,
) -> Plan:
    """Return what this run notifies and how the state changes (ADR 0009)."""
    planner = _Planner(copy.deepcopy(state), observation, config, now)
    planner.work.host = host
    if planner.work.initialized is None:
        return planner.first_run()
    return planner.ordinary_run()


# A holder of conditions: a drive or the tool.
_Holder = DriveRecord | ToolRecord
_Locate = Callable[[State], "_Holder | None"]


@dataclass
class _Outcome:
    """What the planner decided for one holder of conditions."""

    items: list[Item] = field(default_factory=list)
    active: list[Item] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)


class _Planner:
    def __init__(
        self, work: State, observation: Observation, config: Config, now: datetime
    ) -> None:
        self.work = work
        self.observation = observation
        self.config = config
        self.policy: NotifySettings = config.notify
        self.now = now

    # The first run (ADR 0009, FR-516)

    def first_run(self) -> Plan:
        """Record everything as already notified and send one summary.

        If the summary is not handed over, nothing of it is stored: the next
        run is a first run again. Without the summary, everything is stored
        at once.
        """
        empty = State(host=self.work.host, skipped=self._skipped())
        full = copy.deepcopy(empty)
        drives: list[DriveMessage] = []
        unreadable: list[DriveSeen] = []
        for seen in self.observation.drives:
            if seen.presence is Presence.UNREADABLE:
                unreadable.append(seen)
                record = self._record_for_access(full, seen.access)
                record.unreadable_runs = 1
                continue
            if seen.presence is not Presence.READ or seen.snapshot is None:
                continue
            key = self._key(seen)
            record = self._read_record(full, key, seen)
            items = []
            for finding in seen.findings:
                if finding.kind is CheckKind.EVENT:
                    continue
                record.conditions[finding.check] = self._notified(finding)
                items.append(_item(EventType.PROBLEM, finding, since=self.now))
            record.baselines.update(seen.counters)
            if items:
                record.last_notified = self.now
            drives.append(DriveMessage(_info_of_snapshot(key, seen.snapshot), tuple(items)))

        tool_items = []
        for finding in self.observation.tool:
            full.tool.conditions[finding.check] = self._notified(finding)
            tool_items.append(_item(EventType.PROBLEM, finding, since=self.now))
        if tool_items:
            full.tool.last_notified = self.now
        if self.observation.state_reset is not None:
            tool_items.append(_state_reset_item(self.observation.state_reset))
        full.initialized = self.now

        if not self.policy.first_run_summary:
            notifications: tuple[Planned, ...] = ()
            if self.observation.state_reset is not None:
                # The reset is mentioned in the summary that follows it; without
                # one, the tool says it on its own (docs/check-catalog.md).
                reset = _state_reset_item(self.observation.state_reset)
                notifications = (
                    Planned(MessageKind.TOOL, reset.severity, EventType.TOOL, tool=(reset,)),
                )
            return Plan(full, notifications)

        severities = [item.severity for message in drives for item in message.items]
        severities += [item.severity for item in tool_items]
        severity = max(severities, key=RANK.__getitem__, default=Severity.INFO)
        installed = full

        def install(target: State) -> None:
            replacement = copy.deepcopy(installed)
            for name in ("initialized", "drives", "skipped", "tool"):
                setattr(target, name, getattr(replacement, name))

        summary = Planned(
            MessageKind.FIRST_RUN,
            severity,
            EventType.FIRST_RUN,
            drives=tuple(drives),
            tool=tuple(tool_items),
            skipped=self.observation.skipped,
            unreadable=tuple(unreadable),
            state_reset=self.observation.state_reset,
            changes=(install,),
        )
        return Plan(empty, (summary,))

    def _notified(self, finding: Finding) -> ConditionRecord:
        return ConditionRecord(
            severity=finding.severity,
            first_detected=self.now,
            current_value=finding.value,
            threshold=finding.threshold,
            text=finding.text,
            last_notified=self.now,
            notified_severity=finding.severity,
            notified_value=finding.value,
        )

    # An ordinary run

    def ordinary_run(self) -> Plan:
        messages: dict[str, DriveMessage] = {}
        changes: dict[str, list[Change]] = {}
        seen_keys: set[str] = set()

        for seen in self.observation.drives:
            key, message, drive_changes = self._drive(seen)
            if key is None:
                continue
            seen_keys.add(key)
            if message is not None:
                messages[key] = message
                changes[key] = drive_changes

        for key in list(self.work.drives):
            if key in seen_keys:
                continue
            message, drive_changes = self._absent(key)
            if message is not None:
                messages[key] = message
                changes[key] = drive_changes

        self._apply_skipped()
        notifications = self._group(messages, changes)
        tool = self._tool()
        if tool is not None:
            notifications.append(tool)
        return Plan(self.work, tuple(notifications))

    def _drive(self, seen: DriveSeen) -> tuple[str | None, DriveMessage | None, list[Change]]:
        """Plan one device of this run; return its key, its message and the changes."""
        if seen.presence is Presence.READ and seen.snapshot is not None:
            return self._read(seen)
        record_key = self._find_by_access(seen.access)
        if seen.presence is Presence.STANDBY:
            if record_key is not None:
                record = self.work.drives[record_key]
                record.last_seen = self.now
                record.missing_runs = 0
            return record_key, None, []

        # Unreadable: a known drive by the path it was read through, or a
        # device that never answered with an identity, by its path alone.
        if record_key is None:
            record_key = f"device:{seen.access.key}"
            if record_key not in self.work.drives:
                self.work.drives[record_key] = DriveRecord(
                    identity=None,
                    last_access=seen.access,
                    first_seen=self.now,
                    last_seen=self.now,
                )
        record = self.work.drives[record_key]
        record.unreadable_runs += 1
        record.missing_runs = 0
        record.last_seen = self.now
        present: dict[str, Finding] = {}
        enabled = self._enabled(record, DRIVE_UNREADABLE)
        if enabled and record.unreadable_runs >= self.policy.unreadable_runs:
            present[DRIVE_UNREADABLE] = Finding(
                check=DRIVE_UNREADABLE,
                kind=CheckKind.CONDITION,
                severity=CATALOG[DRIVE_UNREADABLE].severity or Severity.WARNING,
                text=(
                    f"no usable SMART data in {record.unreadable_runs} runs in a row: "
                    f"{seen.reason or 'no reason known'}"
                ),
                value=record.unreadable_runs,
            )
        # The other conditions are frozen while the drive cannot be read.
        outcome = self._conditions(
            record,
            present,
            locate=_drive_at(record_key),
            scope={DRIVE_UNREADABLE},
            confirm=lambda _check: 1,
        )
        return (
            record_key,
            self._message(record_key, record, outcome, present=False),
            outcome.changes,
        )

    def _read(self, seen: DriveSeen) -> tuple[str, DriveMessage | None, list[Change]]:
        assert seen.snapshot is not None
        snapshot = seen.snapshot
        key = self._key(seen)
        record = self._read_record(self.work, key, seen)
        settings = effective_checks(self.config, snapshot.identity, snapshot.drive_class)

        present = {
            finding.check: finding
            for finding in seen.findings
            if finding.kind is CheckKind.CONDITION
        }
        # A condition of a check that is switched off goes silently.
        enabled = {name for name, item in settings.items() if item.enabled}
        outcome = self._conditions(
            record,
            present,
            locate=_drive_at(key),
            scope=None,
            enabled=enabled,
            confirm=lambda check: settings[check].confirm_runs if check in settings else 1,
        )
        self._events(key, record, seen, outcome)
        return key, self._message(key, record, outcome, snapshot=snapshot), outcome.changes

    def _events(self, key: str, record: DriveRecord, seen: DriveSeen, outcome: _Outcome) -> None:
        """Plan the events of a drive and keep its baselines (ADR 0009)."""
        for finding in seen.findings:
            if finding.kind is not CheckKind.EVENT or finding.value is None:
                continue
            baseline = record.baselines.get(finding.check)
            last = record.event_notified.get(finding.check)
            if last is not None and self.now - last < self.policy.event_cooldown:
                continue
            outcome.items.append(
                _item(EventType.PROBLEM, finding, previous=baseline, since=self.now)
            )
            outcome.changes.append(_move_baseline(key, finding.check, finding.value, self.now))
        for check, value in seen.counters.items():
            baseline = record.baselines.get(check)
            if baseline is None or value < baseline:
                # A new counter starts from its value (FR-306); one below its
                # baseline was reset by the firmware, and the baseline follows.
                record.baselines[check] = value

    def _absent(self, key: str) -> tuple[DriveMessage | None, list[Change]]:
        """Plan a known drive that this run did not see."""
        record = self.work.drives[key]
        if self.now - record.last_seen > RETENTION:
            del self.work.drives[key]
            return None, []
        if record.identity is None:
            # A device that never answered with an identity and is not
            # unreadable now: its one condition clears, and the record goes
            # once nothing is left of it.
            record.unreadable_runs = 0
            outcome = self._conditions(
                record,
                {},
                locate=_drive_at(key),
                scope={DRIVE_UNREADABLE},
                confirm=lambda _check: 1,
            )
            message = self._message(key, record, outcome, present=False)
            if message is not None:
                # Forgotten once the recovery was handed over.
                outcome.changes.append(_forget(key))
            elif not record.conditions and not record.pending:
                del self.work.drives[key]
            return message, outcome.changes
        if not self.observation.presence_known or record.exempt_from_missing:
            return None, []
        if not self._enabled(record, DRIVE_MISSING):
            return None, []

        record.missing_runs += 1
        if record.missing_runs < self.policy.missing_runs or record.missing_notified:
            return None, []
        item = Item(
            event=EventType.MISSING,
            check=DRIVE_MISSING,
            severity=CATALOG[DRIVE_MISSING].severity or Severity.WARNING,
            text=(
                f"the drive was not found in {record.missing_runs} runs in a row;"
                f" last seen {format_time(record.last_seen)} as {record.last_access.name}"
            ),
            value=record.missing_runs,
            since=record.last_seen,
        )
        active = tuple(_active(check, condition) for check, condition in record.conditions.items())
        message = DriveMessage(_info_of_record(key, record), (item,), active)
        return message, [_mark_missing(key, self.now)]

    def _apply_skipped(self) -> None:
        """Keep the skipped devices for `status`; forget drives that are no longer monitored."""
        self.work.skipped = self._skipped()
        for skipped in self.observation.skipped:
            if skipped.identity is None or skipped.reason not in _UNMONITORED:
                continue
            self.work.drives.pop(identity_key(skipped.identity, skipped.access), None)

    def _skipped(self) -> dict[str, SkippedRecord]:
        previous = self.work.skipped
        result = {}
        for skipped in self.observation.skipped:
            key = skipped.access.key
            before = previous.get(key)
            since = (
                before.since if before is not None and before.reason == skipped.reason else self.now
            )
            result[key] = SkippedRecord(reason=skipped.reason, since=since, detail=skipped.detail)
        return result

    def _tool(self) -> Planned | None:
        """Plan the conditions of the tool, on its pseudo-device (ADR 0009, FR-518)."""
        present = {finding.check: finding for finding in self.observation.tool}
        outcome = self._conditions(
            self.work.tool,
            present,
            locate=lambda state: state.tool,
            scope=None,
            confirm=lambda _c: 1,
        )
        if not outcome.items:
            return None
        severity = max((item.message_severity for item in outcome.items), key=RANK.__getitem__)
        event = next(
            event for event in _EVENT_ORDER if event in {item.event for item in outcome.items}
        )
        return Planned(
            MessageKind.TOOL,
            severity,
            event,
            tool=tuple(outcome.items),
            tool_active=tuple(outcome.active),
            changes=tuple(outcome.changes),
        )

    def _group(
        self, messages: Mapping[str, DriveMessage], changes: Mapping[str, list[Change]]
    ) -> list[Planned]:
        """One message per drive, or one summary above the grouping limit (FR-514, FR-515)."""
        if len(messages) > self.policy.max_drive_notifications:
            severity = max(
                (message.severity for message in messages.values()), key=RANK.__getitem__
            )
            return [
                Planned(
                    MessageKind.SUMMARY,
                    severity,
                    EventType.SUMMARY,
                    drives=tuple(messages.values()),
                    changes=tuple(change for key in messages for change in changes[key]),
                )
            ]
        return [
            Planned(
                MessageKind.DRIVE,
                message.severity,
                message.event,
                drives=(message,),
                changes=tuple(changes[key]),
            )
            for key, message in messages.items()
        ]

    # The rules of one condition (ADR 0009, "When a condition is notified")

    def _conditions(
        self,
        holder: _Holder,
        present: Mapping[str, Finding],
        *,
        locate: _Locate,
        scope: set[str] | None,
        confirm: Callable[[str], int],
        enabled: set[str] | None = None,
    ) -> _Outcome:
        """Apply the rules to the conditions of one drive or of the tool.

        `scope` limits the checks that are looked at; the others are frozen.
        A condition of a check that is no longer enabled is dropped silently:
        switching a check off is not a recovery.
        """
        outcome = _Outcome()
        pending = holder.pending if isinstance(holder, DriveRecord) else {}

        for check, finding in present.items():
            condition = holder.conditions.get(check)
            if condition is None:
                waiting = pending.get(check)
                runs = waiting.seen_runs + 1 if waiting is not None else 1
                first = waiting.first_detected if waiting is not None else self.now
                if runs < confirm(check):
                    pending[check] = PendingRecord(finding.severity, first, runs, finding.value)
                    continue
                pending.pop(check, None)
                condition = ConditionRecord(severity=finding.severity, first_detected=first)
                holder.conditions[check] = condition
            condition.severity = finding.severity
            condition.current_value = finding.value
            condition.threshold = finding.threshold
            condition.text = finding.text
            condition.clear_runs = 0
            event = self._due(holder, check, condition)
            if event is None:
                outcome.active.append(_active(check, condition))
                continue
            outcome.items.append(
                Item(
                    event=event,
                    check=check,
                    severity=condition.severity,
                    text=condition.text,
                    value=condition.current_value,
                    previous=condition.notified_value,
                    threshold=condition.threshold,
                    since=condition.first_detected,
                    previous_severity=condition.notified_severity,
                )
            )
            outcome.changes.append(
                _mark_notified(locate, check, condition.severity, condition.current_value, self.now)
            )

        for check in list(pending):
            if check not in present and (scope is None or check in scope):
                del pending[check]

        for check, condition in list(holder.conditions.items()):
            if check in present or (scope is not None and check not in scope):
                if check not in present:
                    outcome.active.append(_active(check, condition))
                continue
            if enabled is not None and check not in enabled:
                del holder.conditions[check]
                continue
            condition.clear_runs += 1
            if condition.clear_runs < self.policy.clear_runs:
                outcome.active.append(_active(check, condition))
                continue
            if condition.last_notified is None or not self.policy.recovery:
                # Never notified, or recoveries switched off: it goes silently.
                del holder.conditions[check]
                continue
            outcome.items.append(
                Item(
                    event=EventType.RECOVERED,
                    check=check,
                    severity=condition.severity,
                    text=condition.text,
                    value=None,
                    previous=condition.current_value,
                    threshold=condition.threshold,
                    since=condition.first_detected,
                )
            )
            outcome.changes.append(_recover(locate, check, self.now))
        return outcome

    def _due(self, holder: _Holder, check: str, condition: ConditionRecord) -> EventType | None:
        """Return why an active condition is notified now, or `None`."""
        if condition.last_notified is None or condition.notified_severity is None:
            return EventType.PROBLEM
        rank, notified = RANK[condition.severity], RANK[condition.notified_severity]
        if rank > notified:
            # A rise in severity is never held back (FR-511).
            return EventType.ESCALATED
        if rank < notified:
            # A falling severity is not notified; the lower one counts from
            # now on, also for the next worsening and the reminder.
            condition.notified_severity = condition.severity
            condition.notified_value = condition.current_value
        elif self._worsened(holder, check, condition):
            return EventType.WORSENED
        interval = self.policy.reminder.interval(condition.severity.value)
        if interval is not None and self.now - condition.last_notified >= interval:
            return EventType.REMINDER
        return None

    def _worsened(self, holder: _Holder, check: str, condition: ConditionRecord) -> bool:
        """Whether a value rose at the same severity, after the cool-down of the drive (FR-512)."""
        definition = CATALOG.get(check)
        if definition is None or definition.worsening is not Worsening.INCREASE:
            return False
        value, before = condition.current_value, condition.notified_value
        if value is None or before is None or value <= before:
            return False
        last = holder.last_notified
        return last is None or self.now - last >= self.policy.worsening_cooldown

    # Records

    def _key(self, seen: DriveSeen) -> str:
        assert seen.snapshot is not None
        return identity_key(seen.snapshot.identity, seen.access)

    def _read_record(self, state: State, key: str, seen: DriveSeen) -> DriveRecord:
        """Return the record of a drive that was read, updated with what this run saw."""
        snapshot = seen.snapshot
        assert snapshot is not None
        record = state.drives.get(key)
        if record is None:
            record = DriveRecord(
                identity=snapshot.identity,
                last_access=seen.access,
                first_seen=self.now,
                last_seen=self.now,
            )
            state.drives[key] = record
        location = snapshot.location
        record.identity = snapshot.identity
        record.drive_class = snapshot.drive_class
        record.last_access = seen.access
        record.last_seen = self.now
        record.missing_runs = 0
        record.missing_notified = False
        record.unreadable_runs = 0
        # Removable drives, USB drives and drives without a stable identity
        # are never reported as missing (ADR 0009, FR-309).
        record.exempt_from_missing = (
            location.removable is True
            or location.transport == "usb"
            or not snapshot.identity.stable
        )
        record.details = DriveDetails(
            firmware=snapshot.firmware,
            capacity_bytes=snapshot.capacity_bytes,
            location=_location_text(snapshot),
            used_by=_used_by_text(snapshot),
            transport=location.transport,
            removable=location.removable,
        )
        return record

    def _record_for_access(self, state: State, access: Access) -> DriveRecord:
        key = f"device:{access.key}"
        record = state.drives.get(key)
        if record is None:
            record = DriveRecord(
                identity=None, last_access=access, first_seen=self.now, last_seen=self.now
            )
            state.drives[key] = record
        return record

    def _find_by_access(self, access: Access) -> str | None:
        """Return the key of the drive last read through this path, the latest one."""
        matches = [
            (record.last_seen, key)
            for key, record in self.work.drives.items()
            if record.last_access == access
        ]
        return max(matches)[1] if matches else None

    def _enabled(self, record: DriveRecord, check: str) -> bool:
        """Whether a check that the planner raises is enabled for a drive."""
        definition = CATALOG.get(check)
        if definition is None:
            return True
        if record.identity is not None and record.drive_class is not None:
            return effective_checks(self.config, record.identity, record.drive_class)[check].enabled
        return effective_check(self.config, definition, None).enabled

    def _message(
        self,
        key: str,
        record: DriveRecord,
        outcome: _Outcome,
        *,
        snapshot: Snapshot | None = None,
        present: bool = True,
    ) -> DriveMessage | None:
        if not outcome.items:
            return None
        info = (
            _info_of_snapshot(key, snapshot)
            if snapshot is not None
            else _info_of_record(key, record, present=present)
        )
        return DriveMessage(info, tuple(outcome.items), tuple(outcome.active))


def _item(
    event: EventType,
    finding: Finding,
    *,
    previous: int | None = None,
    since: datetime | None = None,
) -> Item:
    return Item(
        event=event,
        check=finding.check,
        severity=finding.severity,
        text=finding.text,
        value=finding.value,
        previous=previous,
        threshold=finding.threshold,
        since=since,
    )


def _active(check: str, condition: ConditionRecord) -> Item:
    """Return an active condition as context for a message; it causes nothing."""
    return Item(
        event=EventType.REMINDER,
        check=check,
        severity=condition.severity,
        text=condition.text,
        value=condition.current_value,
        previous=condition.notified_value,
        threshold=condition.threshold,
        since=condition.first_detected,
    )


def _state_reset_item(reason: str) -> Item:
    """The one-time event `tool.state_reset` (docs/check-catalog.md)."""
    return Item(
        event=EventType.PROBLEM,
        check="tool.state_reset",
        severity=TOOL_CONDITIONS["tool.state_reset"].severity,
        text=f"the state file was set aside and the tool started afresh: {reason}",
    )


def _drive_at(key: str) -> _Locate:
    return lambda state: state.drives.get(key)


def _mark_notified(
    locate: _Locate, check: str, severity: Severity, value: int | None, now: datetime
) -> Change:
    def change(state: State) -> None:
        holder = locate(state)
        if holder is None:
            return
        condition = holder.conditions.get(check)
        if condition is not None:
            condition.last_notified = now
            condition.notified_severity = severity
            condition.notified_value = value
        holder.last_notified = now

    return change


def _recover(locate: _Locate, check: str, now: datetime) -> Change:
    def change(state: State) -> None:
        holder = locate(state)
        if holder is None:
            return
        holder.conditions.pop(check, None)
        holder.last_notified = now

    return change


def _move_baseline(key: str, check: str, value: int, now: datetime) -> Change:
    def change(state: State) -> None:
        record = state.drives.get(key)
        if record is None:
            return
        record.baselines[check] = value
        record.event_notified[check] = now
        record.last_notified = now

    return change


def _mark_missing(key: str, now: datetime) -> Change:
    def change(state: State) -> None:
        record = state.drives.get(key)
        if record is None:
            return
        record.missing_notified = True
        record.last_notified = now

    return change


def _forget(key: str) -> Change:
    def change(state: State) -> None:
        record = state.drives.get(key)
        if record is not None and not record.conditions and not record.pending:
            del state.drives[key]

    return change


def _info_of_snapshot(key: str, snapshot: Snapshot) -> DriveInfo:
    identity = snapshot.identity
    return DriveInfo(
        key=key,
        name=snapshot.access.name,
        type=snapshot.access.type,
        model=identity.model,
        serial=identity.serial,
        wwn=identity.wwn,
        firmware=snapshot.firmware,
        capacity_bytes=snapshot.capacity_bytes,
        drive_class=snapshot.drive_class,
        location=_location_text(snapshot),
        used_by=_used_by_text(snapshot),
        power_on_hours=snapshot.power_on_hours,
    )


def _info_of_record(key: str, record: DriveRecord, *, present: bool = False) -> DriveInfo:
    identity = record.identity
    details = record.details
    return DriveInfo(
        key=key,
        name=record.last_access.name,
        type=record.last_access.type,
        model=None if identity is None else identity.model,
        serial=None if identity is None else identity.serial,
        wwn=None if identity is None else identity.wwn,
        firmware=details.firmware,
        capacity_bytes=details.capacity_bytes,
        drive_class=record.drive_class,
        location=details.location,
        used_by=details.used_by,
        present=present,
        last_seen=record.last_seen,
    )


def _location_text(snapshot: Snapshot) -> str | None:
    """Return where a drive sits: controller and device ID, or the bus path (FR-507)."""
    location = snapshot.location
    if location.controller is not None and location.device_id is not None:
        return f"{location.controller}, device {location.device_id}"
    return location.by_path


def _used_by_text(snapshot: Snapshot) -> str | None:
    """Return what uses a drive, if that is known (FR-110)."""
    membership = snapshot.membership
    parts = []
    if membership.zfs_pool is not None:
        parts.append(f'ZFS pool "{membership.zfs_pool}"')
    if membership.md_array is not None:
        parts.append(f'md array "{membership.md_array}"')
    if membership.volume_group is not None:
        parts.append(f'LVM volume group "{membership.volume_group}"')
    return ", ".join(parts) or None
