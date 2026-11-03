# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for `pve-smart-alert status` (FR-602)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pve_smart_alert import status_report
from pve_smart_alert.state import SkippedRecord, State

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)
PATH = Path("/var/lib/pve-smart-alert/state.json")


def status_of(state: State) -> list[str]:
    return status_report.render(state, path=PATH)


def test_a_skipped_device_is_named_from_its_key() -> None:
    # The key of a skipped device is the device name and the type as a JSON
    # array, like every other key (ADR 0038).
    state = State()
    state.skipped['["/dev/sda", "sat"]'] = SkippedRecord(reason="excluded", since=NOW)

    (line,) = [line for line in status_of(state) if "/dev/sda" in line]

    assert line == "  /dev/sda [sat]: excluded, since 2026-10-12T12:00:00Z"


def test_a_deeply_nested_legacy_key_does_not_crash_status() -> None:
    # A skipped key of a state written by 0.5.0 is a string a device scan
    # reported. Many brackets made `json.loads` fail with RecursionError,
    # which ended `status` with a traceback (ADR 0038).
    state = State()
    state.skipped["[" * 50_000 + "|sat"] = SkippedRecord(reason="excluded", since=NOW)

    (line,) = [line for line in status_of(state) if "excluded" in line]

    assert line.endswith(" [sat]: excluded, since 2026-10-12T12:00:00Z")


def test_a_skipped_device_of_a_state_written_before_the_new_keys_is_named() -> None:
    # A state written by 0.5.0 keeps the old key until the next run rewrites
    # the entry, so `status` has to read both forms.
    state = State()
    state.skipped["/dev/sda|sat"] = SkippedRecord(reason="excluded", since=NOW)

    (line,) = [line for line in status_of(state) if "/dev/sda" in line]

    assert line == "  /dev/sda [sat]: excluded, since 2026-10-12T12:00:00Z"
