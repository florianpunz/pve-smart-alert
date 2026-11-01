# SPDX-License-Identifier: AGPL-3.0-or-later
"""The state store: what the tool remembers between two runs (ADR 0007).

State is one JSON file, `/var/lib/pve-smart-alert/state.json`, owned by root
and readable by root only. Its shape is described in ARCHITECTURE.md
section 9. This module reads it, validates it, migrates an older schema and
replaces it atomically; what the state means is decided by the notification
planner (ADR 0009).

Rules of ADR 0007 that live here:

- Atomic replacement: the new state is written to a temporary file in the
  same directory, flushed to disk and renamed over the old one, so that a
  crash leaves either the old or the new file (NFR-11).
- Corruption: a file that cannot be parsed or fails validation, and a file
  of an unknown newer schema, is renamed to `state.json.corrupt-<timestamp>`
  and the run continues with empty state (NFR-12).
- Migration: each schema version has a function to the next one.
- Timestamps are UTC in ISO 8601; one that lies in the future is read as
  "now", so that a clock jump cannot suppress reminders forever.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from pve_smart_alert.model import NOT_PRINTED, DriveClass, DriveIdentity, Severity

__all__ = [
    "MIGRATIONS",
    "RETENTION",
    "SCHEMA_VERSION",
    "Access",
    "ConditionRecord",
    "DriveDetails",
    "DriveRecord",
    "LastRun",
    "Loaded",
    "PendingRecord",
    "SkippedRecord",
    "State",
    "StateError",
    "ToolRecord",
    "format_time",
    "identity_key",
    "load_state",
    "parse_state",
    "read_state",
    "save_state",
    "state_to_json",
]

#: The schema this version writes. A file of a higher one is set aside
#: like a corrupt file, which keeps a downgrade from misreading it.
SCHEMA_VERSION: Final = 1

#: How long the record of a drive that is no longer seen is kept, so that a
#: returning drive is recognized (ADR 0007).
RETENTION: Final = timedelta(days=90)

# A migration takes the document of one schema version and returns the
# document of the next one.
Migration = Callable[[dict[str, object]], dict[str, object]]

#: The migrations, by the version they start from. Version 1 is the first
#: schema, so there is none yet; the mechanism is tested with its own table.
MIGRATIONS: Final[Mapping[int, Migration]] = {}


class StateError(Exception):
    """A state document that cannot be used."""


@dataclass
class ConditionRecord:
    """One active condition of a drive or of the tool (ARCHITECTURE.md section 7).

    `severity`, `current_value`, `threshold` and `text` are what the last run
    saw. `last_notified`, `notified_severity` and `notified_value` are what
    the last delivered notification said; `None` means that the condition was
    not notified yet. `clear_runs` counts the runs in a row in which the
    condition was absent.
    """

    severity: Severity
    first_detected: datetime
    current_value: int | None = None
    threshold: int | None = None
    text: str = ""
    last_notified: datetime | None = None
    notified_severity: Severity | None = None
    notified_value: int | None = None
    clear_runs: int = 0


@dataclass
class PendingRecord:
    """A condition that was seen but still waits for its confirmation count."""

    severity: Severity
    first_detected: datetime
    seen_runs: int = 1
    value: int | None = None


@dataclass(frozen=True)
class Access:
    """The device name and smartctl type a drive was last read through."""

    name: str
    type: str

    @property
    def key(self) -> str:
        return f"{self.name}|{self.type}"


@dataclass
class DriveDetails:
    """What a notification about a drive shows when the drive cannot be read now."""

    firmware: str | None = None
    capacity_bytes: int | None = None
    location: str | None = None
    used_by: str | None = None
    transport: str | None = None
    removable: bool | None = None


@dataclass
class DriveRecord:
    """Everything the tool remembers about one drive (ADR 0007).

    `identity` is `None` for a device that has never answered with an
    identity; such a record is keyed by its device name and type and only
    ever holds the condition that it is unreadable.
    """

    identity: DriveIdentity | None
    last_access: Access
    first_seen: datetime
    last_seen: datetime
    drive_class: DriveClass | None = None
    missing_runs: int = 0
    unreadable_runs: int = 0
    missing_notified: bool = False
    exempt_from_missing: bool = False
    last_notified: datetime | None = None
    baselines: dict[str, int] = field(default_factory=dict)
    event_notified: dict[str, datetime] = field(default_factory=dict)
    conditions: dict[str, ConditionRecord] = field(default_factory=dict)
    pending: dict[str, PendingRecord] = field(default_factory=dict)
    details: DriveDetails = field(default_factory=DriveDetails)


@dataclass
class SkippedRecord:
    """A device that discovery skipped, kept for `pve-smart-alert status` only."""

    reason: str
    since: datetime
    detail: str | None = None


@dataclass
class ToolRecord:
    """The conditions of the tool itself, on its pseudo-device (ADR 0009)."""

    conditions: dict[str, ConditionRecord] = field(default_factory=dict)
    last_notified: datetime | None = None


@dataclass
class LastRun:
    """What the last run did (FR-602, FR-606)."""

    started: datetime
    finished: datetime
    result: str
    drives_evaluated: int = 0
    drives_skipped: int = 0
    drives_failed: int = 0
    notifications_sent: int = 0
    notifications_failed: int = 0


@dataclass
class State:
    """The whole state of one node (ARCHITECTURE.md section 9).

    `initialized` is `None` until the first run has been completed; the
    planner treats a state without it as a first run (ADR 0009).
    """

    host: str = ""
    initialized: datetime | None = None
    last_run: LastRun | None = None
    drives: dict[str, DriveRecord] = field(default_factory=dict)
    skipped: dict[str, SkippedRecord] = field(default_factory=dict)
    tool: ToolRecord = field(default_factory=ToolRecord)


@dataclass(frozen=True)
class Loaded:
    """What loading the state file brought.

    `reset` says why the state is empty although a file was there, and
    `set_aside` where that file went; both are `None` for a good file and
    for a missing one.
    """

    state: State
    reset: str | None = None
    set_aside: Path | None = None


def identity_key(identity: DriveIdentity, access: Access | None = None) -> str:
    """Return the key of a drive in the state file (ADR 0005, ADR 0007).

    Model and serial number, or model and WWN when there is no serial
    number. A drive without either has no stable identity and is keyed by
    the path it was read through as well, because two such drives may well
    be two drives.
    """
    if identity.serial is not None:
        return f"{identity.model}|{identity.serial}"
    if identity.wwn is not None:
        return f"{identity.model}|wwn:{identity.wwn}"
    where = f"|device:{access.key}" if access is not None else ""
    return f"{identity.model}{where}"


def load_state(
    path: Path,
    *,
    now: datetime,
    migrations: Mapping[int, Migration] = MIGRATIONS,
    schema: int = SCHEMA_VERSION,
) -> Loaded:
    """Load the state file for a run (ADR 0007).

    A missing file is an empty state. A file that cannot be used is renamed
    to `<name>.corrupt-<timestamp>` and the run goes on with an empty state;
    `Loaded.reset` says why. A file that cannot even be renamed is left in
    place and overwritten by the next save.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Loaded(State())
    except (OSError, UnicodeDecodeError) as error:
        return _set_aside(path, f"the state file cannot be read: {error}", now=now)

    try:
        state = parse_state(text, now=now, migrations=migrations, schema=schema)
    except StateError as error:
        return _set_aside(path, str(error), now=now)
    return Loaded(state)


def read_state(
    path: Path, *, now: datetime, schema: int = SCHEMA_VERSION
) -> tuple[State | None, str | None]:
    """Read the state file without changing anything, for `status` and a dry run.

    Returns the state, or `None` and the reason why there is none. A file
    that is not there is not an error: there is simply no state yet.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError) as error:
        return None, f"the state file cannot be read: {error}"
    try:
        return parse_state(text, now=now, schema=schema), None
    except StateError as error:
        return None, str(error)


def save_state(state: State, path: Path) -> None:
    """Replace the state file atomically (ADR 0007, NFR-11)."""
    text = _escaped(json.dumps(state_to_json(state), indent=2, ensure_ascii=False)) + "\n"
    write_private(path, text)


def write_private(path: Path, text: str) -> None:
    """Replace a file of the tool atomically, readable by root only (ADR 0007).

    The file holds serial numbers, so neither it nor the directory it lies in
    may be readable by others. The directory is created with mode 0700, and
    one that an earlier build or a run by hand created with the mode of the
    umask is corrected. The temporary file is created next to the target with
    mode 0600, written, flushed to disk and renamed over the target; the
    directory is flushed as well, so that the rename survives a power loss. A
    failure leaves the old file as it was and removes the temporary one.
    Raises `OSError`.
    """
    _private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(temporary).unlink()
        raise
    _sync_directory(path.parent)


def _private_directory(directory: Path) -> None:
    """Create the directory of a file of the tool, and keep it readable by root only."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o777 != 0o700:
        directory.chmod(0o700)


def format_time(value: datetime) -> str:
    """Return a timestamp as the state file writes it: UTC, ISO 8601, whole seconds."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_state(
    text: str,
    *,
    now: datetime,
    migrations: Mapping[int, Migration] = MIGRATIONS,
    schema: int = SCHEMA_VERSION,
) -> State:
    """Return the state of a document, migrated to the current schema.

    Raises `StateError` when the document cannot be used.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise StateError(f"the state file is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise StateError("the state file does not hold a JSON object")

    version = document.get("schema")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise StateError("the state file names no valid schema version")
    if version > schema:
        raise StateError(
            f"the state file has the schema version {version}, which is newer than"
            f" the version {schema} this program reads"
        )
    while version < schema:
        migration = migrations.get(version)
        if migration is None:
            raise StateError(f"there is no migration from the schema version {version}")
        document = migration(document)
        version += 1
        document["schema"] = version

    try:
        return _state_of(document, _Reader(now))
    except (KeyError, TypeError, ValueError) as error:
        raise StateError(f"the state file does not validate: {error}") from error


def state_to_json(state: State) -> dict[str, object]:
    """Return the document of a state, in the shape of ARCHITECTURE.md section 9."""
    return {
        "schema": SCHEMA_VERSION,
        "host": state.host,
        "initialized": _time_or_none(state.initialized),
        "last_run": _last_run_to_json(state.last_run),
        "drives": {key: _drive_to_json(record) for key, record in state.drives.items()},
        "skipped": {
            key: {"reason": record.reason, "since": format_time(record.since)}
            | ({"detail": record.detail} if record.detail is not None else {})
            for key, record in state.skipped.items()
        },
        "tool": {
            "conditions": {
                key: _condition_to_json(record) for key, record in state.tool.conditions.items()
            },
            "last_notified": _time_or_none(state.tool.last_notified),
        },
    }


def _escaped(text: str) -> str:
    """Return JSON text with the characters that are not printed as escapes.

    The strings of drives are kept as they came (ADR 0005); escaped, the
    characters that `without_controls` replaces put nothing on a terminal
    that shows the file, and the rest stays readable with `cat` (ADR 0007,
    ARCHITECTURE.md section 14). `json.dumps` escapes the C0 controls inside
    a string already, so one below DEL is the whitespace between the values;
    outside its strings JSON is ASCII, and an escape means the same character
    inside a string, so the file reads back as it was written.
    """
    return "".join(
        json.dumps(character)[1:-1]
        if character >= "\x7f" and unicodedata.category(character) in NOT_PRINTED
        else character
        for character in text
    )


def _set_aside(path: Path, reason: str, *, now: datetime) -> Loaded:
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        path.rename(target)
    except OSError:
        return Loaded(State(), reset=reason)
    return Loaded(State(), reset=reason, set_aside=target)


def _sync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _time_or_none(value: datetime | None) -> str | None:
    return None if value is None else format_time(value)


def _last_run_to_json(run: LastRun | None) -> dict[str, object] | None:
    if run is None:
        return None
    return {
        "started": format_time(run.started),
        "finished": format_time(run.finished),
        "result": run.result,
        "drives_evaluated": run.drives_evaluated,
        "drives_skipped": run.drives_skipped,
        "drives_failed": run.drives_failed,
        "notifications_sent": run.notifications_sent,
        "notifications_failed": run.notifications_failed,
    }


def _drive_to_json(record: DriveRecord) -> dict[str, object]:
    identity = record.identity
    details = record.details
    return {
        "identity": None
        if identity is None
        else {"model": identity.model, "serial": identity.serial, "wwn": identity.wwn},
        "class": None if record.drive_class is None else record.drive_class.value,
        "last_access": {"name": record.last_access.name, "type": record.last_access.type},
        "first_seen": format_time(record.first_seen),
        "last_seen": format_time(record.last_seen),
        "missing_runs": record.missing_runs,
        "unreadable_runs": record.unreadable_runs,
        "missing_notified": record.missing_notified,
        "exempt_from_missing": record.exempt_from_missing,
        "last_notified": _time_or_none(record.last_notified),
        "baselines": dict(record.baselines),
        "event_notified": {key: format_time(value) for key, value in record.event_notified.items()},
        "conditions": {key: _condition_to_json(value) for key, value in record.conditions.items()},
        "pending": {
            key: {
                "severity": value.severity.value,
                "first_detected": format_time(value.first_detected),
                "seen_runs": value.seen_runs,
                "value": value.value,
            }
            for key, value in record.pending.items()
        },
        "details": {
            "firmware": details.firmware,
            "capacity_bytes": details.capacity_bytes,
            "location": details.location,
            "used_by": details.used_by,
            "transport": details.transport,
            "removable": details.removable,
        },
    }


def _condition_to_json(record: ConditionRecord) -> dict[str, object]:
    return {
        "severity": record.severity.value,
        "first_detected": format_time(record.first_detected),
        "current_value": record.current_value,
        "threshold": record.threshold,
        "text": record.text,
        "last_notified": _time_or_none(record.last_notified),
        "notified_severity": None
        if record.notified_severity is None
        else record.notified_severity.value,
        "notified_value": record.notified_value,
        "clear_runs": record.clear_runs,
    }


class _Reader:
    """Reads the values of a document strictly; a wrong type raises `TypeError`."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def time(self, node: Mapping[str, object], key: str) -> datetime:
        value = node[key]
        if not isinstance(value, str):
            raise TypeError(f'"{key}" must be a timestamp')
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError(f'"{key}" has no time zone')
        # A timestamp in the future is read as now (ADR 0007).
        return min(parsed.astimezone(UTC), self.now)

    def time_or_none(self, node: Mapping[str, object], key: str) -> datetime | None:
        return None if node.get(key) is None else self.time(node, key)

    @staticmethod
    def text(node: Mapping[str, object], key: str) -> str:
        value = node[key]
        if not isinstance(value, str):
            raise TypeError(f'"{key}" must be a string')
        return value

    @staticmethod
    def text_or_none(node: Mapping[str, object], key: str) -> str | None:
        value = node.get(key)
        if value is not None and not isinstance(value, str):
            raise TypeError(f'"{key}" must be a string')
        return value

    @staticmethod
    def number(node: Mapping[str, object], key: str, default: int | None = None) -> int:
        value = node.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f'"{key}" must be a whole number')
        return value

    @staticmethod
    def number_or_none(node: Mapping[str, object], key: str) -> int | None:
        value = node.get(key)
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f'"{key}" must be a whole number')
        return value

    @staticmethod
    def flag(node: Mapping[str, object], key: str) -> bool:
        value = node.get(key, False)
        if not isinstance(value, bool):
            raise TypeError(f'"{key}" must be true or false')
        return value

    @staticmethod
    def flag_or_none(node: Mapping[str, object], key: str) -> bool | None:
        value = node.get(key)
        if value is not None and not isinstance(value, bool):
            raise TypeError(f'"{key}" must be true or false')
        return value

    @staticmethod
    def table(node: Mapping[str, object], key: str) -> Mapping[str, object]:
        value = node.get(key, {})
        if not isinstance(value, dict):
            raise TypeError(f'"{key}" must be an object')
        return value

    @staticmethod
    def tables(node: Mapping[str, object], key: str) -> dict[str, Mapping[str, object]]:
        value = _Reader.table(node, key)
        for name, entry in value.items():
            if not isinstance(entry, dict):
                raise TypeError(f'"{key}.{name}" must be an object')
        return dict(value)  # type: ignore[arg-type]


def _state_of(document: Mapping[str, object], read: _Reader) -> State:
    last_run = document.get("last_run")
    if last_run is not None and not isinstance(last_run, dict):
        raise TypeError('"last_run" must be an object')
    tool = read.table(document, "tool")
    return State(
        host=read.text_or_none(document, "host") or "",
        initialized=read.time_or_none(document, "initialized"),
        last_run=None if last_run is None else _last_run_of(last_run, read),
        drives={
            key: _drive_of(entry, read) for key, entry in read.tables(document, "drives").items()
        },
        skipped={
            key: SkippedRecord(
                reason=read.text(entry, "reason"),
                since=read.time(entry, "since"),
                detail=read.text_or_none(entry, "detail"),
            )
            for key, entry in read.tables(document, "skipped").items()
        },
        tool=ToolRecord(
            conditions={
                key: _condition_of(entry, read)
                for key, entry in read.tables(tool, "conditions").items()
            },
            last_notified=read.time_or_none(tool, "last_notified"),
        ),
    )


def _last_run_of(node: Mapping[str, object], read: _Reader) -> LastRun:
    return LastRun(
        started=read.time(node, "started"),
        finished=read.time(node, "finished"),
        result=read.text(node, "result"),
        drives_evaluated=read.number(node, "drives_evaluated", 0),
        drives_skipped=read.number(node, "drives_skipped", 0),
        drives_failed=read.number(node, "drives_failed", 0),
        notifications_sent=read.number(node, "notifications_sent", 0),
        notifications_failed=read.number(node, "notifications_failed", 0),
    )


def _drive_of(node: Mapping[str, object], read: _Reader) -> DriveRecord:
    identity_node = node.get("identity")
    identity = None
    if identity_node is not None:
        if not isinstance(identity_node, dict):
            raise TypeError('"identity" must be an object')
        identity = DriveIdentity.of(
            read.text(identity_node, "model"),
            serial=read.text_or_none(identity_node, "serial"),
            wwn=read.text_or_none(identity_node, "wwn"),
        )
    access = read.table(node, "last_access")
    drive_class = read.text_or_none(node, "class")
    details = read.table(node, "details")
    baselines = read.table(node, "baselines")
    return DriveRecord(
        identity=identity,
        last_access=Access(read.text(access, "name"), read.text(access, "type")),
        first_seen=read.time(node, "first_seen"),
        last_seen=read.time(node, "last_seen"),
        drive_class=None if drive_class is None else DriveClass(drive_class),
        missing_runs=read.number(node, "missing_runs", 0),
        unreadable_runs=read.number(node, "unreadable_runs", 0),
        missing_notified=read.flag(node, "missing_notified"),
        exempt_from_missing=read.flag(node, "exempt_from_missing"),
        last_notified=read.time_or_none(node, "last_notified"),
        baselines={key: read.number(baselines, key) for key in baselines},
        event_notified={
            key: read.time(read.table(node, "event_notified"), key)
            for key in read.table(node, "event_notified")
        },
        conditions={
            key: _condition_of(entry, read)
            for key, entry in read.tables(node, "conditions").items()
        },
        pending={
            key: PendingRecord(
                severity=Severity(read.text(entry, "severity")),
                first_detected=read.time(entry, "first_detected"),
                seen_runs=read.number(entry, "seen_runs", 1),
                value=read.number_or_none(entry, "value"),
            )
            for key, entry in read.tables(node, "pending").items()
        },
        details=DriveDetails(
            firmware=read.text_or_none(details, "firmware"),
            capacity_bytes=read.number_or_none(details, "capacity_bytes"),
            location=read.text_or_none(details, "location"),
            used_by=read.text_or_none(details, "used_by"),
            transport=read.text_or_none(details, "transport"),
            removable=read.flag_or_none(details, "removable"),
        ),
    )


def _condition_of(node: Mapping[str, object], read: _Reader) -> ConditionRecord:
    notified = read.text_or_none(node, "notified_severity")
    return ConditionRecord(
        severity=Severity(read.text(node, "severity")),
        first_detected=read.time(node, "first_detected"),
        current_value=read.number_or_none(node, "current_value"),
        threshold=read.number_or_none(node, "threshold"),
        text=read.text_or_none(node, "text") or "",
        last_notified=read.time_or_none(node, "last_notified"),
        notified_severity=None if notified is None else Severity(notified),
        notified_value=read.number_or_none(node, "notified_value"),
        clear_runs=read.number(node, "clear_runs", 0),
    )
