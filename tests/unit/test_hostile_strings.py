# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hostile strings in drive data (ARCHITECTURE.md section 14, ROADMAP.md M7).

A drive, its firmware or a controller writes the strings that smartctl and
lsblk pass on: model, serial number, firmware, vendor and the label of a
pool. Before such a string reaches a terminal, the journal, a notification
or the bridge, its control characters are gone and it is cut to a length,
so that it cannot move the cursor, colour the terminal, start a line of its
own or fill a message.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest
from frame import ScenarioHost
from hosts import Host

from pve_smart_alert import cli
from pve_smart_alert.discovery import discover
from pve_smart_alert.model import MAX_FIELD_VALUE
from pve_smart_alert.scan_report import render

SMARTCTL = Path("/usr/sbin/smartctl")

#: A model that tries everything at once: an ANSI escape that colours the
#: terminal, the 8-bit form of the same introducer (C1 control CSI), a
#: carriage return that overwrites the line, a newline that starts a line of
#: its own, a NUL, the template syntax of Handlebars and shell
#: metacharacters.
HOSTILE_MODEL: Final = "EVIL\x1b[31mRED\x9b2J\rFAKE\nInjected: line\x00 {{body}} $(reboot); `id`"
#: A serial number with the C1 control NEL and DEL.
HOSTILE_SERIAL: Final = "ANON-SN-0001\x85X\x7f"
#: A firmware string far longer than any real one.
LONG_FIRMWARE: Final = "F" * 5000

#: Characters that must never reach any output.
FORBIDDEN: Final = tuple(
    chr(code) for code in (*range(0, 9), *range(11, 32), 127, *range(128, 160))
)


def hostile_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    host = Host.of_node(tmp_path, monkeypatch, "pve7")
    drive = host.drive("sda.json")
    drive["model_name"] = HOSTILE_MODEL
    drive["serial_number"] = HOSTILE_SERIAL
    drive["firmware_version"] = LONG_FIRMWARE
    (host.recording / "sda.json").write_text(json.dumps(drive), encoding="utf-8")
    return host


def assert_clean(text: str) -> None:
    found = sorted({f"U+{ord(character):04X}" for character in text if character in FORBIDDEN})
    assert not found, found


def test_scan_shows_no_control_character_of_a_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hostile_host(tmp_path, monkeypatch)
    discovery = discover(host.config(), runner=host, paths=host.paths)

    lines = render(discovery, smartctl_path=SMARTCTL)

    text = "\n".join(lines)
    assert_clean(text.replace("\n", ""))
    model = next(line for line in lines if line.startswith("  Model:"))
    assert "Injected" in model
    assert not any(line.startswith("Injected") for line in lines)
    firmware = next(line for line in lines if line.startswith("  Firmware:"))
    assert len(firmware) < 300


def hostile_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScenarioHost:
    """The scenario `pending-sectors` with the hostile strings in every step."""
    host = ScenarioHost(tmp_path, monkeypatch, "pending-sectors")
    for step in host.steps.values():
        path = step / "sda.json"
        if not path.exists():
            continue
        drive = json.loads(path.read_text(encoding="utf-8"))
        drive["model_name"] = HOSTILE_MODEL
        drive["serial_number"] = HOSTILE_SERIAL
        drive["firmware_version"] = LONG_FIRMWARE
        path.write_text(json.dumps(drive), encoding="utf-8")
    host.install()
    return host


def test_a_notification_carries_no_control_character_of_a_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = hostile_scenario(tmp_path, monkeypatch)

    (first,) = host.run("01-healthy")
    (warning,) = host.run("03-pending-3")

    for notification in (first, warning):
        assert_clean(notification.subject)
        assert "\n" not in notification.subject
        assert_clean(notification.body.replace("\n", ""))
        assert not any(line.startswith("Injected") for line in notification.body.splitlines())
        for value in notification.fields_for().values():
            assert_clean(value)
            assert "\n" not in value
            assert "," not in value
            assert len(value) <= MAX_FIELD_VALUE
    # The template syntax and the shell metacharacters stay text: the bridge
    # hands them to the notification system as data of a fixed template.
    assert "{{body}} $(reboot); `id`" in warning.body
    assert all(len(line) < 300 for line in warning.body.splitlines())


def test_status_and_the_dry_run_show_no_control_character_of_a_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    host = hostile_scenario(tmp_path, monkeypatch)
    host.run("01-healthy")
    host.step("03-pending-3")
    capsys.readouterr()

    cli.main(["check", "--dry-run"])
    dry_run = capsys.readouterr()
    cli.main(["status"])
    status = capsys.readouterr()

    for captured in (dry_run, status):
        for text in (captured.out, captured.err):
            assert_clean(text.replace("\n", ""))
            assert not any(line.startswith("Injected") for line in text.splitlines())


def test_the_journal_line_of_a_run_carries_no_string_of_a_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The summary line of a run counts; it names no drive (FR-606).
    host = hostile_scenario(tmp_path, monkeypatch)
    capsys.readouterr()

    host.run("03-pending-3")

    out = capsys.readouterr().out
    summary = next(line for line in out.splitlines() if line.startswith("pve-smart-alert: run"))
    assert "EVIL" not in summary
    assert_clean(out.replace("\n", ""))


def test_a_pool_label_of_lsblk_is_shown_without_its_control_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The label of a ZFS pool is read from the disk by lsblk, so it is as
    # untrusted as a model.
    host = Host.of_node(tmp_path, monkeypatch, "pve7")
    host.change_lsblk("sda", fstype="zfs_member", label="tank\x1b]0;owned\x07\nInjected")
    discovery = discover(host.config(), runner=host, paths=host.paths)

    lines = render(discovery, smartctl_path=SMARTCTL)

    assert_clean("".join(lines))
    used = next(line for line in lines if line.startswith("  Used by:"))
    assert "Injected" in used
