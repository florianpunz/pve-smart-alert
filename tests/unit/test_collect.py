# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the collector (ADR 0004).

They run the real process code against `tests/fake-smartctl`, which replays
the anonymized recordings of the test cluster (ADR 0016).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Final

import pytest

from pve_smart_alert.collect import Status, collect_drive, drive_command, is_ata, judge
from pve_smart_alert.config import Detail, SmartctlSettings

TESTS: Final = Path(__file__).resolve().parent.parent
FAKE: Final = TESTS / "fake-smartctl"
RECORDINGS: Final = TESTS / "fixtures" / "smartctl" / "direct"


@pytest.fixture
def recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the recording of pve7 that the fake smartctl replays."""
    directory = tmp_path / "recording"
    shutil.copytree(RECORDINGS / "test-cluster-pve7", directory)
    monkeypatch.setenv("FAKE_SMARTCTL_RECORDING", str(directory))
    monkeypatch.setenv("FAKE_SMARTCTL_LOG", str(tmp_path / "calls.log"))
    return directory


def behave(recording: Path, file: str, **behavior: object) -> None:
    """Make the fake answer differently for one file."""
    (recording / "behavior.json").write_text(json.dumps({file: behavior}), encoding="utf-8")


def settings(**changes: object) -> SmartctlSettings:
    values: dict[str, object] = {"path": FAKE, "timeout_seconds": 10.0, "detail": Detail.EXTENDED}
    values.update(changes)
    return SmartctlSettings(**values)  # type: ignore[arg-type]


def calls(recording: Path) -> list[list[str]]:
    log = recording.parent / "calls.log"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_a_recorded_ata_drive_is_read(recording: Path) -> None:
    collected = collect_drive("/dev/sda", "sat", protocol="ATA", settings=settings())

    assert collected.status is Status.OK
    assert collected.exit_status == 0
    assert collected.document is not None
    assert collected.document["serial_number"] == "ANON-SN-0001"
    assert collected.smartctl_version == (7, 5)
    # The standby check is passed to smartctl itself (FR-203).
    assert calls(recording) == [
        ["--json=c", "--xall", "--device=sat", "--nocheck=standby", "/dev/sda"]
    ]


def test_an_nvme_drive_is_read_through_its_controller(recording: Path) -> None:
    collected = collect_drive("/dev/nvme0", "nvme", protocol="NVMe", settings=settings())

    assert collected.status is Status.OK
    assert calls(recording) == [["--json=c", "--xall", "--device=nvme", "/dev/nvme0"]]


def test_the_basic_detail_reads_less(recording: Path) -> None:
    collect_drive("/dev/sda", "sat", protocol="ATA", settings=settings(detail=Detail.BASIC))

    assert calls(recording)[0][1] == "--all"


@pytest.mark.usefixtures("recording")
def test_a_drive_that_cannot_be_opened_is_unreadable() -> None:
    # A manual device with a name that does not exist (acceptance step 4 of M2).
    collected = collect_drive("/dev/sdz", "sat", settings=settings())

    assert collected.status is Status.UNREADABLE
    assert collected.exit_status == 2
    assert collected.reason == "Smartctl open device: /dev/sdz failed: No such device"
    assert collected.document is None


def test_a_sleeping_drive_is_not_read(recording: Path) -> None:
    behave(recording, "sda.json", standby="STANDBY")

    collected = collect_drive("/dev/sda", "sat", protocol="ATA", settings=settings())

    assert collected.status is Status.STANDBY
    assert collected.reason == "STANDBY"
    assert collected.document is None


def test_a_drive_that_does_not_answer_is_ended(recording: Path) -> None:
    behave(recording, "sda.json", delay_seconds=30)

    collected = collect_drive(
        "/dev/sda", "sat", protocol="ATA", settings=settings(timeout_seconds=0.5)
    )

    assert collected.status is Status.UNREADABLE
    assert collected.reason == "smartctl did not answer within 0.5 seconds"
    # It costs at most the timeout, not the 30 seconds (FR-202).
    assert collected.duration_seconds < 5


def test_an_answer_that_is_not_json_is_unreadable(recording: Path) -> None:
    behave(recording, "nvme0.json", stdout="smartctl: something went wrong\n", exit_status=0)

    collected = collect_drive("/dev/nvme0", "nvme", settings=settings())

    assert collected.status is Status.UNREADABLE
    assert collected.reason == "smartctl answered without valid JSON"


def test_a_missing_smartctl_is_unreadable(tmp_path: Path) -> None:
    collected = collect_drive("/dev/sda", "sat", settings=settings(path=tmp_path / "smartctl"))

    assert collected.status is Status.UNREADABLE
    assert collected.reason is not None
    assert collected.reason.startswith("smartctl could not be started")


@pytest.mark.parametrize(
    ("exit_status", "status"),
    [
        (0, Status.OK),
        # A missing extended log is common and tolerated (ADR 0004).
        (4, Status.OK),
        # Bits 3 to 7 are hints; the checks read the JSON instead.
        (0b1101000, Status.OK),
        (1, Status.UNREADABLE),
        (2, Status.UNREADABLE),
        (6, Status.UNREADABLE),
    ],
)
def test_the_exit_status_is_a_bit_mask(exit_status: int, status: Status) -> None:
    stdout = json.dumps({"json_format_version": [1, 0], "smartctl": {"version": [7, 5]}})

    assert judge(stdout, exit_status, command=["smartctl"], duration=0.1).status is status


def test_an_unreadable_drive_names_the_first_message() -> None:
    stdout = json.dumps(
        {
            "json_format_version": [1, 0],
            "smartctl": {
                "messages": [
                    {
                        "string": "Read Device Identity failed: Input/output error\n",
                        "severity": "error",
                    }
                ]
            },
        }
    )

    collected = judge(stdout, 2, command=["smartctl"], duration=0.1)

    assert collected.reason == "Read Device Identity failed: Input/output error"


def test_another_json_format_is_unreadable() -> None:
    stdout = json.dumps({"json_format_version": [2, 0]})

    collected = judge(stdout, 0, command=["smartctl"], duration=0.1)

    assert collected.status is Status.UNREADABLE
    assert collected.reason == "smartctl writes JSON format 2, not 1"


@pytest.mark.parametrize(
    ("device_type", "ata"),
    [
        ("sat", True),
        ("ata", True),
        ("sat+megaraid,3", True),
        ("usbjmicron,0", True),
        ("nvme", False),
        ("scsi", False),
        ("megaraid,0", False),
        ("areca,2/1", False),
    ],
)
def test_the_standby_check_applies_to_ata_drives(device_type: str, ata: bool) -> None:
    assert is_ata(device_type) is ata


def test_the_protocol_of_the_scan_decides_over_the_type() -> None:
    assert is_ata("scsi", "ATA") is True
    assert is_ata("sat", "SCSI") is False


def test_the_command_takes_name_and_type_as_found() -> None:
    command = drive_command("/dev/bus/0", "sat+megaraid,12", settings=settings())

    assert command == [
        str(FAKE),
        "--json=c",
        "--xall",
        "--device=sat+megaraid,12",
        "--nocheck=standby",
        "/dev/bus/0",
    ]


def test_a_sas_drive_behind_megaraid_is_read_without_the_standby_check() -> None:
    # The standby check is an ATA command; a SAS drive behind the
    # controller is read as `megaraid,N` (ADR 0004, ADR 0028).
    command = drive_command("/dev/bus/6", "megaraid,8", settings=settings(), protocol="SCSI")

    assert command == [str(FAKE), "--json=c", "--xall", "--device=megaraid,8", "/dev/bus/6"]
