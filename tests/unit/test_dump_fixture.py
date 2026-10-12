# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for `pve-smart-alert dump-fixture` (FR-604, NFR-14, ADR 0023).

The host has identifiers in the form of real ones, made up for the tests:
the archive must contain none of them.
"""

from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from hosts import REAL_SERIALS, REAL_VALUES, Host, write_real_looking_recording

from pve_smart_alert import cli
from pve_smart_alert.anonymize import AnonymizationError
from pve_smart_alert.config import Config, ManualDevice
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
        "lsblk --json --output NAME,KNAME,TYPE,TRAN,RM,HOTPLUG,FSTYPE,LABEL"
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
