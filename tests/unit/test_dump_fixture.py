# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for `pve-smart-alert dump-fixture` (FR-604, NFR-14, ADR 0023).

The host has identifiers in the form of real ones, made up for the tests:
the archive must contain none of them.
"""

from __future__ import annotations

import errno
import json
import os
import stat
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final

import pytest
from hosts import REAL_SERIALS, REAL_VALUES, Host, write_real_looking_recording

from pve_smart_alert import cli
from pve_smart_alert.anonymize import AnonymizationError
from pve_smart_alert.config import Config, ManualDevice
from pve_smart_alert.discovery import Outcome
from pve_smart_alert.dump import Dump, DumpError, dump_fixture

NOW: Final = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)
NAME: Final = "pve-smart-alert-fixture-pve9-20261007T120000Z"


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    source = tmp_path / "source"
    write_real_looking_recording(source)
    return Host(tmp_path, monkeypatch, source)


def dump(
    host: Host, tmp_path: Path, selected: list[str] | None = None, **discovery: object
) -> Dump:
    """Dump the host; `selected` names the devices, `discovery` is the configuration."""
    return dump_fixture(
        host.config(**discovery),  # type: ignore[arg-type]
        devices=selected,
        output=tmp_path / "out",
        node="pve9",
        now=NOW,
        runner=host,
        paths=host.paths,
    )


def contents(archive: Path) -> dict[str, str]:
    """Return the files of an archive by their path below its directory."""
    with tarfile.open(archive, "r:gz") as tar:
        result = {}
        for member in tar.getmembers():
            stream = tar.extractfile(member)
            assert stream is not None
            top, name = member.name.split("/", 1)
            assert top == NAME
            result[name] = stream.read().decode("utf-8")
    return result


def test_all_devices_are_written_anonymized(host: Host, tmp_path: Path) -> None:
    # Acceptance step 3 of M2.
    result = dump(host, tmp_path)

    assert result.archive == tmp_path / "out" / f"{NAME}.tar.gz"
    assert result.devices == ("/dev/sda", "/dev/nvme0")
    files = contents(result.archive)
    assert sorted(files) == ["lsblk.json", "nvme0.json", "recording.json", "scan.json", "sda.json"]
    everything = "\n".join(files.values()).lower()
    for value in REAL_VALUES:
        assert value.lower() not in everything
    sda = json.loads(files["sda.json"])
    assert sda["serial_number"] == "ANON-SN-0001"
    assert sda["wwn"] == {"naa": 5, "oui": 9528, "id": 1}


def test_the_archive_records_what_the_tool_runs(host: Host, tmp_path: Path) -> None:
    files = contents(dump(host, tmp_path).archive)

    recording = json.loads(files["recording.json"])
    assert recording["node"] == "pve9"
    assert recording["collected"] == "20261007T120000Z"
    assert recording["collected_with"].startswith("pve-smart-alert dump-fixture ")
    assert recording["license"] == "AGPL-3.0-or-later"
    commands = {entry["file"]: entry["command"] for entry in recording["files"]}
    assert commands["lsblk.json"] == (
        "lsblk --json --output NAME,KNAME,TYPE,TRAN,RM,HOTPLUG,FSTYPE,LABEL,VENDOR,MODEL"
    )
    assert [entry["file"] for entry in recording["files"]] == [
        "scan.json",
        "sda.json",
        "nvme0.json",
        "lsblk.json",
    ]


def test_the_drives_are_read_as_the_collector_reads_them(host: Host, tmp_path: Path) -> None:
    dump(host, tmp_path)

    calls = [json.loads(line) for line in host.log.read_text(encoding="utf-8").splitlines()]
    assert ["--scan-open", "--json=c"] in calls
    assert ["--json=c", "--xall", "--device=sat", "--nocheck=standby", "/dev/sda"] in calls
    assert ["--json=c", "--xall", "--device=nvme", "/dev/nvme0"] in calls


def test_a_recording_names_the_type_of_the_call_and_replays(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # smartctl writes `3ware` without the disk number into the output of a
    # drive read as `3ware,1`, and `sat` for a SATA drive read through cciss
    # or aacraid (os_linux.cpp and scsiata.cpp of 7.5). The recording names
    # the type of the call, so that the fake smartctl replays the archive
    # with the same call (ADR 0016).
    drive = host.drive("sda.json")
    drive["device"] = {
        "name": "/dev/twa0",
        "info_name": "/dev/twa0 [3ware_disk_01]",
        "type": "3ware",
        "protocol": "ATA",
    }
    host.add_file("twa0.json", drive, device="/dev/twa0", device_type="3ware,1")
    entries = (ManualDevice("/dev/twa0", "3ware,1"),)

    files = contents(dump(host, tmp_path, ["/dev/twa0"], devices=entries).archive)

    recording = json.loads(files["recording.json"])
    (entry,) = [
        item for item in recording["files"] if item["file"] not in ("scan.json", "lsblk.json")
    ]
    assert (entry["device"], entry["type"]) == ("/dev/twa0", "3ware,1")
    replay = tmp_path / "replay"
    replay.mkdir()
    for name, text in files.items():
        (replay / name).write_text(text, encoding="utf-8")
    replayed = Host(tmp_path / "again", monkeypatch, replay)
    (found,) = [
        item
        for item in replayed.discover(devices=entries).devices
        if item.candidate.name == "/dev/twa0"
    ]
    assert found.outcome is Outcome.MONITORED


def test_selected_devices_only(host: Host, tmp_path: Path) -> None:
    result = dump(host, tmp_path, selected=["/dev/nvme0"])

    assert result.devices == ("/dev/nvme0",)
    assert "sda.json" not in contents(result.archive)


def test_an_unknown_device_writes_nothing(host: Host, tmp_path: Path) -> None:
    with pytest.raises(DumpError, match="not found by the scan or as a manual device: /dev/sdq"):
        dump(host, tmp_path, selected=["/dev/sdq"])

    assert not (tmp_path / "out").exists()


def test_a_device_that_cannot_be_read_is_recorded_with_its_messages(
    host: Host, tmp_path: Path
) -> None:
    # What smartctl answers for such a device is what a recording is for.
    result = dump(host, tmp_path, selected=["/dev/sdz"], devices=(ManualDevice("/dev/sdz", "sat"),))

    sdz = json.loads(contents(result.archive)["sdz.json"])
    assert sdz["smartctl"]["messages"][0]["string"].startswith("Smartctl open device: /dev/sdz")


def _unreadable(name: str) -> dict[str, object]:
    """Return what smartctl answers for a drive in standby: no serial number."""
    return {
        "json_format_version": [1, 0],
        "smartctl": {
            "version": [7, 5],
            "argv": ["smartctl", "--json=c", "--xall", "--device=sat", "--nocheck=standby", name],
            "messages": [
                {"string": "Device is in STANDBY mode, exit(2)", "severity": "information"}
            ],
            "exit_status": 2,
        },
    }


def test_a_manual_device_named_by_a_by_id_link_carries_no_serial(
    host: Host, tmp_path: Path
) -> None:
    # A by-id link has the serial number in its name. The drive is behind a
    # controller and sleeps: neither its output nor lsblk teaches the serial
    # number, so the name itself may not leak it either (ADR 0023,
    # ARCHITECTURE.md section 14).
    serial = REAL_SERIALS[0]
    host.change_lsblk("sda", serial=None)
    name = f"/dev/disk/by-id/ata-Samsung_SSD_850_EVO_250GB_{serial}"
    host.add_file("byid.json", _unreadable(name), device=name, device_type="sat")

    result = dump(host, tmp_path, selected=[name], devices=(ManualDevice(name, "sat"),))

    with tarfile.open(result.archive, "r:gz") as tar:
        member_names = [member.name for member in tar.getmembers()]
    files = contents(result.archive)
    everything = "\n".join([*member_names, *files.values()])
    assert serial not in everything
    recording = json.loads(files["recording.json"])
    (entry,) = [
        item for item in recording["files"] if item["file"] not in ("scan.json", "lsblk.json")
    ]
    assert entry["device"].startswith("/dev/anon")
    assert entry["file"] == f"{PurePosixPath(entry['device']).name}.json"


def test_a_readable_drive_named_by_a_by_id_link_is_recorded(host: Host, tmp_path: Path) -> None:
    # The serial number of the link is learned from the drive as well; the
    # recording must replace it in the name like in any other text.
    serial = REAL_SERIALS[0]
    name = f"/dev/disk/by-id/ata-Samsung_SSD_850_EVO_250GB_{serial}"
    drive = host.drive("sda.json")
    drive["device"] = {
        "name": name,
        "info_name": f"{name} [SAT]",
        "type": "sat",
        "protocol": "ATA",
    }
    smartctl = drive["smartctl"]
    assert isinstance(smartctl, dict)
    smartctl["argv"] = [
        "smartctl",
        "--json=c",
        "--xall",
        "--device=sat",
        "--nocheck=standby",
        name,
    ]
    host.add_file("byid.json", drive, device=name, device_type="sat")

    result = dump(host, tmp_path, selected=[name], devices=(ManualDevice(name, "sat"),))

    files = contents(result.archive)
    assert serial not in "\n".join([*files, *files.values()])
    recording = json.loads(files["recording.json"])
    (entry,) = [
        item for item in recording["files"] if item["file"] not in ("scan.json", "lsblk.json")
    ]
    recorded = json.loads(files[entry["file"]])
    assert recorded["serial_number"] == "ANON-SN-0001"
    assert recorded["device"]["name"] == entry["device"]


def test_the_archive_is_readable_by_root_only(host: Host, tmp_path: Path) -> None:
    # It carries the identifiers of the host until they are reviewed nowhere
    # else; a file in a shared directory may not be readable by everyone.
    archive = dump(host, tmp_path).archive

    assert archive.stat().st_mode & 0o777 == 0o600


def test_the_archive_is_flushed_before_the_rename(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A power loss between the write and the rename must not leave a partial
    # archive: the file is flushed, then renamed, then the directory is
    # flushed (ADR 0007, ADR 0023).
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = Path.replace

    def fsync(descriptor: int) -> None:
        events.append("directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file")
        real_fsync(descriptor)

    def replace(self: Path, target: Path) -> Path:
        events.append("rename")
        return real_replace(self, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)

    dump(host, tmp_path)

    assert events == ["file", "rename", "directory"]


def test_a_directory_that_cannot_be_flushed_does_not_fail_the_dump(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Some filesystems do not flush a directory. The archive is already in
    # place then, and the run must not claim that nothing was written.
    real_fsync = os.fsync

    def fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "the filesystem cannot flush a directory")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)

    result = dump(host, tmp_path)

    assert result.archive.exists()


def test_a_failed_flush_leaves_the_old_archive_and_no_temporary(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    old = out / f"{NAME}.tar.gz"
    old.write_bytes(b"old archive")

    def fsync(descriptor: int) -> None:
        del descriptor
        raise OSError(errno.ENOSPC, "no space left")

    monkeypatch.setattr(os, "fsync", fsync)

    with pytest.raises(OSError, match="no space left"):
        dump(host, tmp_path)

    assert old.read_bytes() == b"old archive"
    assert not [path for path in out.iterdir() if path.name.endswith(".tmp")]


def test_a_symlink_at_the_archive_path_is_replaced(host: Host, tmp_path: Path) -> None:
    # A predictable name in a directory others can write to may be a symlink
    # to a file of the administrator: the dump writes its own file instead.
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep me", encoding="utf-8")
    (out / f"{NAME}.tar.gz").symlink_to(victim)

    dump(host, tmp_path)

    assert victim.read_text(encoding="utf-8") == "keep me"
    assert not (out / f"{NAME}.tar.gz").is_symlink()


def test_nothing_is_written_when_a_real_value_would_be_left(host: Host, tmp_path: Path) -> None:
    # A WWN in a form the anonymizer does not know: it fails closed.
    host.change_lsblk("sda", wwn="naa.5002538e40a1b2c3")

    with pytest.raises(AnonymizationError, match="still contains a real value: WWN"):
        dump(host, tmp_path)

    assert not (tmp_path / "out").exists()


def test_a_failed_scan_writes_nothing(host: Host, tmp_path: Path) -> None:
    host.behave("scan.json", stdout="not json", exit_status=0)

    with pytest.raises(DumpError, match="without valid JSON"):
        dump(host, tmp_path)


# The command


def install(monkeypatch: pytest.MonkeyPatch, host: Host) -> None:
    monkeypatch.setattr(cli, "load_config", host.config)
    monkeypatch.setattr(cli, "node_name", lambda: "pve9")

    def dump_here(config: Config, **keywords: object) -> Dump:
        return dump_fixture(config, runner=host, paths=host.paths, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "dump_fixture", dump_here)


def test_the_command_writes_the_archive(
    host: Host,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install(monkeypatch, host)

    assert cli.main(["dump-fixture", "--all", "--output", str(tmp_path / "out")]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert out.startswith(f"Written:   {tmp_path / 'out'}/pve-smart-alert-fixture-pve9-")
    assert "Devices:   /dev/sda, /dev/nvme0\n" in out
    assert "look at the archive before you share it" in out
    archives = list((tmp_path / "out").glob("*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as tar:
        text = "".join(
            stream.read().decode("utf-8")
            for member in tar.getmembers()
            if (stream := tar.extractfile(member)) is not None
        )
    for serial in REAL_SERIALS:
        assert serial not in text


def test_the_command_needs_all_or_devices() -> None:
    for arguments in (["dump-fixture"], ["dump-fixture", "--all", "/dev/sda"]):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(arguments)
        assert exit_info.value.code == cli.EXIT_USAGE


def test_the_command_says_that_nothing_was_written(
    host: Host,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install(monkeypatch, host)

    assert cli.main(["dump-fixture", "/dev/sdq", "--output", str(tmp_path)]) == cli.EXIT_PROBLEM
    assert "nothing was written: not found by the scan" in capsys.readouterr().err
