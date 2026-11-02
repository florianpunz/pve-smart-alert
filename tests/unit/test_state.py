# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the state store (ADR 0007, NFR-11, NFR-12).

Atomic replacement, the handling of a corrupt file and of an unknown schema,
the migration between schema versions, and the clamping of timestamps that
lie in the future.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pve_smart_alert.model import DriveClass, DriveIdentity, Severity
from pve_smart_alert.state import (
    SCHEMA_VERSION,
    Access,
    ConditionRecord,
    DriveDetails,
    DriveRecord,
    LastRun,
    PendingRecord,
    SkippedRecord,
    State,
    StateError,
    format_time,
    identity_key,
    load_state,
    parse_state,
    read_state,
    save_state,
    state_to_json,
)

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)


def full_state() -> State:
    """Return a state that uses every part of the schema."""
    identity = DriveIdentity.of(
        "Samsung SSD 870 EVO 1TB", serial="ANON-SN-0001", wwn="5000000000000001"
    )
    earlier = NOW - timedelta(hours=2)
    record = DriveRecord(
        identity=identity,
        last_access=Access("/dev/sdb", "sat"),
        first_seen=earlier,
        last_seen=NOW,
        drive_class=DriveClass.SSD,
        missing_runs=1,
        unreadable_runs=0,
        missing_notified=False,
        exempt_from_missing=False,
        last_notified=earlier,
        baselines={"ata.crc_errors": 12, "ata.error_log": 0},
        event_notified={"ata.crc_errors": earlier},
        conditions={
            "ata.reallocated_sectors": ConditionRecord(
                severity=Severity.WARNING,
                first_detected=earlier,
                current_value=8,
                threshold=5,
                text="8 sectors",
                last_notified=earlier,
                notified_severity=Severity.WARNING,
                notified_value=8,
                clear_runs=0,
            )
        },
        pending={
            "temperature": PendingRecord(
                severity=Severity.WARNING, first_detected=NOW, seen_runs=1, value=61
            )
        },
        details=DriveDetails(
            firmware="SVT02B6Q",
            capacity_bytes=1_000_204_886_016,
            location="pci-0000:00:17.0-ata-2",
            used_by='LVM volume group "pve"',
            transport="sata",
            removable=False,
        ),
    )
    return State(
        host="pve1",
        initialized=earlier,
        last_run=LastRun(
            started=NOW,
            finished=NOW,
            result="ok",
            drives_evaluated=1,
            drives_skipped=1,
            notifications_sent=1,
        ),
        drives={identity_key(identity): record},
        skipped={Access("/dev/sda", "scsi").key: SkippedRecord(reason="excluded", since=earlier)},
    )


def test_a_state_survives_a_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = full_state()

    save_state(state, path)
    loaded = load_state(path, now=NOW)

    assert loaded.reset is None
    assert loaded.state == state


def test_the_file_has_the_documented_shape(tmp_path: Path) -> None:
    # ARCHITECTURE.md section 9: readable with cat and jq.
    path = tmp_path / "state.json"
    save_state(full_state(), path)

    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["schema"] == SCHEMA_VERSION
    key = identity_key(DriveIdentity.of("Samsung SSD 870 EVO 1TB", serial="ANON-SN-0001"))
    drive = document["drives"][key]
    assert drive["identity"]["serial"] == "ANON-SN-0001"
    assert drive["conditions"]["ata.reallocated_sectors"]["notified_value"] == 8
    assert drive["last_seen"] == "2026-10-12T12:00:00Z"


def test_the_file_is_readable_by_root_only(tmp_path: Path) -> None:
    # ADR 0007: the file holds serial numbers (NFR-13, NFR-14).
    path = tmp_path / "state.json"
    save_state(State(), path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_missing_file_is_an_empty_state(tmp_path: Path) -> None:
    loaded = load_state(tmp_path / "state.json", now=NOW)

    assert loaded.state == State()
    assert loaded.reset is None
    assert loaded.state.initialized is None


def test_a_failed_write_leaves_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # NFR-11: a crash at any point leaves the old or the new file. Here the
    # rename fails, which is the last step before the new file is in place.
    path = tmp_path / "state.json"
    save_state(full_state(), path)
    before = path.read_text(encoding="utf-8")

    def broken_replace(_source: object, _target: object) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(Path, "replace", broken_replace)
    with pytest.raises(OSError, match="simulated crash"):
        save_state(State(host="other"), path)

    assert path.read_text(encoding="utf-8") == before
    # No temporary file is left behind.
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.json"]


def test_a_write_interrupted_before_the_rename_leaves_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    save_state(full_state(), path)
    before = path.read_text(encoding="utf-8")

    def broken_fsync(_descriptor: int) -> None:
        raise OSError("simulated power loss")

    monkeypatch.setattr("pve_smart_alert.state.os.fsync", broken_fsync)
    with pytest.raises(OSError, match="simulated power loss"):
        save_state(State(host="other"), path)

    assert path.read_text(encoding="utf-8") == before
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.json"]


def test_the_directory_is_created_for_root_only(tmp_path: Path) -> None:
    path = tmp_path / "lib" / "state.json"

    save_state(State(), path)

    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "does not hold a JSON object"),
        ('{"drives": {}}', "no valid schema version"),
        ('{"schema": 1, "drives": {"x": {"identity": 5}}}', "does not validate"),
        (
            '{"schema": 1, "tool": {"conditions": {"tool.scan_failed": {"severity": "bad",'
            ' "first_detected": "2026-10-12T12:00:00Z"}}}}',
            "does not validate",
        ),
    ],
)
def test_a_corrupt_file_is_set_aside(tmp_path: Path, content: str, reason: str) -> None:
    # ADR 0007, NFR-12: renamed, the run continues with empty state.
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")

    loaded = load_state(path, now=NOW)

    assert loaded.state == State()
    assert loaded.reset is not None
    assert reason in loaded.reset
    assert not path.exists()
    assert loaded.set_aside == tmp_path / "state.json.corrupt-20261012T120000Z"
    assert loaded.set_aside.read_text(encoding="utf-8") == content


def test_a_file_of_a_newer_schema_is_set_aside(tmp_path: Path) -> None:
    # ADR 0007: an unknown newer version is treated like corruption, so that
    # a downgrade cannot misread it.
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema": SCHEMA_VERSION + 1}), encoding="utf-8")

    loaded = load_state(path, now=NOW)

    assert loaded.reset is not None
    assert "newer" in loaded.reset
    assert loaded.set_aside is not None


def test_a_file_that_cannot_be_renamed_is_left_for_the_next_save(tmp_path: Path) -> None:
    directory = tmp_path / "lib"
    directory.mkdir()
    path = directory / "state.json"
    path.write_text("{broken", encoding="utf-8")
    directory.chmod(0o500)
    try:
        if os.access(directory, os.W_OK):
            pytest.skip("the test runs with rights that ignore the file mode")
        loaded = load_state(path, now=NOW)
    finally:
        directory.chmod(0o700)

    assert loaded.reset is not None
    assert loaded.set_aside is None
    assert loaded.state == State()


def test_an_older_schema_is_migrated_step_by_step() -> None:
    # ADR 0007: each schema version has a migration function to the next one.
    # Version 1 is the first schema, so the mechanism is tested with a table
    # of its own: from 1 to 3 through 2.
    def one_to_two(document: dict[str, object]) -> dict[str, object]:
        return {**document, "host": "renamed-in-2"}

    def two_to_three(document: dict[str, object]) -> dict[str, object]:
        document = dict(document)
        document["host"] = f"{document['host']}-then-3"
        return document

    document = state_to_json(State(host="pve1"))
    document["schema"] = 1

    state = parse_state(
        json.dumps(document), now=NOW, migrations={1: one_to_two, 2: two_to_three}, schema=3
    )

    assert state.host == "renamed-in-2-then-3"


def test_a_missing_migration_is_an_error() -> None:
    document = state_to_json(State())
    document["schema"] = 1
    with pytest.raises(StateError, match="no migration"):
        parse_state(json.dumps(document), now=NOW, migrations={}, schema=2)


def test_a_relative_path_does_not_change_the_mode_of_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `save_state` accepts any path. A bare file name makes the directory `.`;
    # the tool does not change a directory it does not own (ADR 0012).
    tmp_path.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    save_state(State(), Path("state.json"))

    assert (tmp_path / "state.json").exists()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755


def test_a_state_of_schema_1_is_migrated_to_the_new_keys() -> None:
    # ADR 0037: the key of every record is rebuilt from the record itself, so
    # that a build upgrade finds every drive again and reports none missing.
    document = state_to_json(full_state())
    document["schema"] = 1
    drives = document["drives"]
    assert isinstance(drives, dict)
    ((key, record),) = drives.items()
    assert isinstance(record, dict)
    identity = record["identity"]
    assert isinstance(identity, dict)
    old_key = f"{identity['model']}|{identity['serial']}"
    document["drives"] = {old_key: record}

    migrated = parse_state(json.dumps(document), now=NOW)

    assert list(migrated.drives) == [key]


def test_an_identity_less_record_of_a_real_0_5_0_state_is_found() -> None:
    # The fixture was written by the code of 0.5.0 (SOURCES.md). It keys the
    # device that never answered the old way; after loading, the record is
    # found under the key a run computes (ADR 0038).
    path = Path(__file__).parents[1] / "fixtures" / "state" / "dev5-unreadable-device.json"

    loaded = parse_state(path.read_text(encoding="utf-8"), now=NOW)

    access = Access("/dev/sdz", "sat")
    record = loaded.drives[f"device:{access.key}"]
    assert record.identity is None
    assert record.last_access == access
    assert record.unreadable_runs == 2


def test_a_timestamp_in_the_future_is_read_as_now(tmp_path: Path) -> None:
    # ADR 0007: a clock jump must not suppress reminders forever.
    path = tmp_path / "state.json"
    state = full_state()
    record = next(iter(state.drives.values()))
    record.conditions["ata.reallocated_sectors"].last_notified = NOW + timedelta(days=400)
    save_state(state, path)

    loaded = load_state(path, now=NOW)

    condition = next(iter(loaded.state.drives.values())).conditions["ata.reallocated_sectors"]
    assert condition.last_notified == NOW


def test_reading_for_status_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")

    state, error = read_state(path, now=NOW)

    assert state is None
    assert error is not None
    assert path.read_text(encoding="utf-8") == "{broken"
    assert read_state(tmp_path / "absent.json", now=NOW) == (None, None)


def test_the_key_of_a_drive() -> None:
    # ADR 0005: model and serial number; the WWN without a serial number; a
    # drive without either is keyed by its path as well.
    assert identity_key(DriveIdentity.of("M", serial="S")) == '["M", "serial", "S"]'
    assert identity_key(DriveIdentity.of("M", wwn="0x5000AB")) == '["M", "wwn", "5000ab"]'
    assert identity_key(DriveIdentity.of("M"), Access("/dev/sda", "sat")) == (
        '["M", "device", "/dev/sda", "sat"]'
    )


def test_two_accesses_that_differ_do_not_share_a_key() -> None:
    # The name and the type of a device of the scan need not be valid, and
    # both can contain the character a key was joined with. A record of a
    # device that never answered is keyed by them, so that key is a JSON
    # array as well (ADR 0038).
    assert Access("/dev/a|b", "c").key != Access("/dev/a", "b|c").key


def test_two_drives_cannot_share_a_key() -> None:
    # A model or serial number can contain the character a key was joined
    # with; two drives must never share one record (ADR 0037).
    assert identity_key(DriveIdentity.of("A|B", serial="C")) != identity_key(
        DriveIdentity.of("A", serial="B|C")
    )
    assert identity_key(DriveIdentity.of("M", serial="wwn:5000ab")) != identity_key(
        DriveIdentity.of("M", wwn="5000ab")
    )


def test_timestamps_are_utc_with_whole_seconds() -> None:
    value = datetime(2026, 10, 12, 14, 0, 0, 123456, tzinfo=UTC)
    assert format_time(value) == "2026-10-12T14:00:00Z"
