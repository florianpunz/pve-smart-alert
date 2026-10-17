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
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from frame import ScenarioHost
from hosts import Host

from pve_smart_alert import cli
from pve_smart_alert.config import TransportName
from pve_smart_alert.discovery import discover
from pve_smart_alert.discovery.sources import Candidate, Source
from pve_smart_alert.model import (
    MAX_FIELD_VALUE,
    EventType,
    Notification,
    Severity,
    normalize,
    printable,
    sanitize_field_value,
    without_controls,
)
from pve_smart_alert.scan_report import render
from pve_smart_alert.transports import TransportOutcome
from pve_smart_alert.transports.mail import MailTransport, build_message

SMARTCTL = Path("/usr/sbin/smartctl")

#: A model that tries everything at once: an ANSI escape that colours the
#: terminal, the 8-bit form of the same introducer (C1 control CSI), a
#: carriage return that overwrites the line, a newline that starts a line of
#: its own, a NUL, the template syntax of Handlebars and shell
#: metacharacters, a lone surrogate, which no output can encode, and a
#: letter outside ASCII that is printed as it is.
HOSTILE_MODEL: Final = (
    "EVIL\x1b[31mRED\x9b2J\rFAKE\nInjected: line\x00\t{{body}} $(reboot); `id`\u202e\ud800\u00e9"
)
#: A serial number with the C1 control NEL and DEL.
HOSTILE_SERIAL: Final = "ANON-SN-0001\x85X\x7f"
#: A firmware string far longer than any real one, which smartctl does not
#: normalize as it does model and serial number, with a line of its own.
LONG_FIRMWARE: Final = "F\nInjected: firmware" + "F" * 5000

#: Characters that must never reach any output: the C0 controls but newline,
#: which only a line break of the tool itself may write, DEL, the C1 controls,
#: and the controls of the direction of text and the invisible characters of
#: Unicode (category Cf), such as RIGHT-TO-LEFT OVERRIDE and ZERO WIDTH SPACE,
#: with the line and paragraph separators.
FORBIDDEN: Final = (
    *(chr(code) for code in (*range(0, 10), *range(11, 32), 127, *range(128, 160))),
    "\u061c",
    "\u200b",
    "\u200e",
    "\u200f",
    "\u2028",
    "\u2029",
    *(chr(code) for code in range(0x202A, 0x202F)),
    *(chr(code) for code in range(0x2066, 0x206A)),
    "\ufeff",
    "\ud800",
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
    # What a terminal, the journal or a pipe receives is UTF-8.
    text.encode("utf-8")


def strings_of(value: object) -> Iterator[str]:
    """Yield every string in the structured data of a notification."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_of(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from strings_of(item)


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


def test_the_journal_lines_of_a_run_carry_no_control_character_of_a_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A run logs a line per notification with its subject, which names the
    # drive, and a summary line that counts (FR-606).
    host = hostile_scenario(tmp_path, monkeypatch)
    host.run("01-healthy")
    capsys.readouterr()

    host.run("03-pending-3")

    out = capsys.readouterr().out
    sent = next(line for line in out.splitlines() if line.startswith("sent ("))
    assert "EVIL" in sent
    summary = next(line for line in out.splitlines() if line.startswith("pve-smart-alert: run"))
    assert "EVIL" not in summary
    assert_clean(out.replace("\n", ""))
    assert not any(line.startswith("Injected") for line in out.splitlines())


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


HOSTILE_VOLUME: Final = "MR9361\x1b[2J\x9b31m\nInjected" + "M" * 5000


def test_the_inquiry_data_of_a_skipped_volume_reach_scan_and_status_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A device skipped as a logical volume is named with the vendor and model
    # that lsblk shows, which come from the controller (ADR 0028).
    host = hostile_scenario(tmp_path, monkeypatch)
    for step in host.steps.values():
        path = step / "lsblk.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        for device in document["blockdevices"]:
            if device.get("name") == "sda":
                device.update(vendor="LSI", model=HOSTILE_VOLUME)
        path.write_text(json.dumps(document), encoding="utf-8")
    host.run("01-healthy")
    capsys.readouterr()

    cli.main(["scan"])
    scan = capsys.readouterr().out
    cli.main(["status"])
    status = capsys.readouterr().out

    assert "logical-volume (lsblk vendor LSI, model MR9361" in scan
    for text in (scan, status):
        assert_clean(text.replace("\n", ""))
        assert not any(line.startswith("Injected") for line in text.splitlines())
        assert all(len(line) < 300 for line in text.splitlines())


def test_a_device_name_of_the_scan_that_is_not_one_reaches_no_output_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A name of the scan that may not reach smartctl is reported as
    # unreadable (ARCHITECTURE.md section 5); it is still shown, cleaned, and
    # a mail with it is still built.
    host = ScenarioHost(tmp_path, monkeypatch, "pending-sectors")
    for step in host.steps.values():
        path = step / "scan.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["devices"].append(
            {"name": "/dev/sdz\x1b[31m\nInjected: fake line", "type": "sat", "protocol": "ATA"}
        )
        path.write_text(json.dumps(document), encoding="utf-8")
    host.install()
    mails: list[str] = []
    original = host.transport.send

    def send(notification: Notification) -> TransportOutcome:
        mails.append(build_message(notification, recipient="root"))
        return original(notification)

    monkeypatch.setattr(host.transport, "send", send)
    capsys.readouterr()

    notifications = [
        notification
        for name in ("01-healthy", "02-healthy", "03-pending-3")
        for notification in host.run(name)
    ]

    out = capsys.readouterr().out
    assert mails
    for text in (out, *mails):
        assert_clean(text.replace("\n", ""))
        assert not any(line.startswith("Injected") for line in text.splitlines())
    # The bridge hands the data to templates that an administrator overrides.
    values = [value for notification in notifications for value in strings_of(notification.data)]
    assert any(value.startswith("/dev/sdz") for value in values)
    for value in values:
        assert_clean(value)
        assert "\n" not in value


@pytest.mark.parametrize(
    "value", ["EVIL\x9bX", "EVIL\x85X", "EVIL\u202eX", "EVIL\u200bX", "EVIL\ud800X"]
)
def test_a_field_value_holds_no_control_or_format_character(value: str) -> None:
    # The device field and the driver of a SCSI host are cleaned here only
    # (ADR 0008, ARCHITECTURE.md section 14).
    assert sanitize_field_value(value) == "EVIL X"
    assert printable(value, limit=200) == "EVIL X"
    assert without_controls(value) == "EVIL X"


def test_the_text_of_a_transport_reaches_test_notification_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The log of the notification system and the error of a transport can
    # carry what a remote server answered.
    host = ScenarioHost(tmp_path, monkeypatch, "pending-sectors")
    host.install()

    def send(_notification: Notification) -> TransportOutcome:
        return TransportOutcome(
            delivered=False,
            transport=TransportName.PVE_NOTIFY,
            duration_seconds=0.0,
            error="refused: \x1b[2J550\nInjected: fake line",
            log_lines=("smtp says \x1b]0;owned\x07",),
        )

    monkeypatch.setattr(host.transport, "send", send)
    capsys.readouterr()

    cli.main(["test-notification"])

    out = capsys.readouterr().out
    assert "refused:" in out
    assert_clean(out.replace("\n", ""))
    assert not any(line.startswith("Injected") for line in out.splitlines())


def test_the_state_file_holds_no_control_character_of_a_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The state keeps the strings of a drive as they came, so that its
    # identity does not change (ADR 0005); in the file they are escaped, so
    # that `cat state.json` prints none of them (ADR 0007).
    host = hostile_scenario(tmp_path, monkeypatch)
    host.run("01-healthy")

    text = host.state_path.read_text(encoding="utf-8")

    assert_clean(text.replace("\n", ""))
    assert "\\u009b" in text
    # What is not cleaned stays readable with `cat`.
    assert "\u00e9" in text
    # Read back, the identity is the one the drive reported (ADR 0005).
    models = [drive["identity"]["model"] for drive in json.loads(text)["drives"].values()]
    assert normalize(HOSTILE_MODEL) in models


def test_the_answer_of_a_transport_reaches_the_journal_lines_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The reason of a fallback and the error of a transport can carry what
    # a remote server or the bridge answered (FR-606).
    host = ScenarioHost(tmp_path, monkeypatch, "pending-sectors")
    host.install()
    answers = iter(
        (
            TransportOutcome(
                delivered=True,
                transport=TransportName.MAIL,
                duration_seconds=0.0,
                fallback_reason="bridge said \x1b[2J\nInjected: fake line",
            ),
            TransportOutcome(
                delivered=False,
                transport=TransportName.PVE_NOTIFY,
                duration_seconds=0.0,
                error="refused: \x9b31m\nInjected: fake line",
            ),
        )
    )
    monkeypatch.setattr(host.transport, "send", lambda _notification: next(answers))
    capsys.readouterr()

    host.run("01-healthy")
    host.run("03-pending-3")

    out = capsys.readouterr().out
    assert any(line.startswith("sent (mail, because bridge said") for line in out.splitlines())
    assert any(line.startswith("not delivered (refused:") for line in out.splitlines())
    assert_clean(out.replace("\n", ""))
    assert not any(line.startswith("Injected") for line in out.splitlines())


def test_a_mail_that_cannot_be_built_is_not_delivered(tmp_path: Path) -> None:
    # The renderer never writes such a subject; a defect that does is
    # reported as a notification not delivered instead of ending the run.
    sendmail = tmp_path / "sendmail"
    sendmail.write_text("", encoding="utf-8")

    def runner(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the mail command must not be started")

    transport = MailTransport(sendmail_path=sendmail, runner=runner)  # type: ignore[arg-type]
    notification = Notification(
        event=EventType.PROBLEM,
        severity=Severity.WARNING,
        node="pve1",
        subject="first line\nInjected: header",
        body="body",
    )

    outcome = transport.send(notification)

    assert not outcome.delivered
    assert outcome.error is not None
    assert outcome.error.startswith("the mail could not be built")


def test_the_progress_line_names_a_device_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # On a terminal, each device is named before it is read.
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    cli._reading(Candidate("/dev/sdz\x1b[31m\nInjected", "sat\x9b2J", Source.SCAN))

    err = capsys.readouterr().err
    assert err.startswith("reading /dev/sdz")
    assert_clean(err.replace("\n", ""))
    assert not any(line.startswith("Injected") for line in err.splitlines())


def test_the_dry_run_shows_what_a_drive_says_about_its_health_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A SAS drive that fails its verdict names the informational exception
    # in its own words, which the finding quotes (checks.py, `_health`).
    host = ScenarioHost(tmp_path, monkeypatch, "hba-sas")
    path = host.steps["02-grown-defects"] / "sdc.json"
    drive = json.loads(path.read_text(encoding="utf-8"))
    drive["smart_status"] = {
        "passed": False,
        "scsi": {"asc": 93, "ascq": 0, "ie_string": "FAILING\x1b[2J\x9b31m\nInjected: line"},
    }
    path.write_text(json.dumps(drive), encoding="utf-8")
    host.install()
    host.run("01-healthy")
    host.step("02-grown-defects")
    capsys.readouterr()

    cli.main(["check", "--dry-run"])

    out = capsys.readouterr().out
    assert "FAILING" in out
    assert_clean(out.replace("\n", ""))
    assert not any(line.startswith("Injected") for line in out.splitlines())
