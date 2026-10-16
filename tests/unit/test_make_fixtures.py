# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for `scripts/make_fixtures.py` (ADR 0023).

The archives are built here in the layout of `scripts/collect-node-data.sh`,
with identifiers that are made up in the form of real ones.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPOSITORY_ROOT / "scripts" / "make_fixtures.py"
TOP: Final = "pve-smart-alert-data-pve9-20261007T120000Z"
SERIALS: Final = ("S2R5NX0H123456A", "S35ENX0J654321")


def scan() -> dict[str, object]:
    # The scan lists the NVMe drive first, so it gets the first numbers.
    return {
        "json_format_version": [1, 0],
        "smartctl": {"version": [7, 5], "argv": ["smartctl", "--scan-open", "--json=c"]},
        "devices": [
            {"name": "/dev/nvme0", "info_name": "/dev/nvme0", "type": "nvme", "protocol": "NVMe"},
            {"name": "/dev/sda", "info_name": "/dev/sda [SAT]", "type": "sat", "protocol": "ATA"},
        ],
    }


def sata() -> dict[str, object]:
    return {
        "smartctl": {
            "version": [7, 5],
            "argv": ["smartctl", "-x", "--json=c", "-d", "sat", "/dev/sda"],
        },
        "device": {"name": "/dev/sda", "type": "sat", "protocol": "ATA"},
        "model_name": "Samsung SSD 850 EVO 250GB",
        "serial_number": SERIALS[0],
        "wwn": {"naa": 5, "oui": 9528, "id": 0xE40A1B2C3},
        "rotation_rate": 0,
    }


def nvme() -> dict[str, object]:
    return {
        "smartctl": {
            "version": [7, 5],
            "argv": ["smartctl", "-x", "--json=c", "-d", "nvme", "/dev/nvme0"],
        },
        "device": {"name": "/dev/nvme0", "type": "nvme", "protocol": "NVMe"},
        "model_name": "SAMSUNG MZVLW256HEHP-000L2",
        "serial_number": SERIALS[1],
        "nvme_namespaces": [{"id": 1, "eui64": {"oui": 9528, "ext_id": 0x5B71B02A7F}}],
    }


def lsblk() -> dict[str, object]:
    return {
        "blockdevices": [
            {"name": "sda", "type": "disk", "serial": SERIALS[0], "wwn": "0x5002538e40a1b2c3"},
            {
                "name": "nvme0n1",
                "type": "disk",
                "serial": SERIALS[1],
                "wwn": "eui.0025385b71b02a7f",
            },
        ]
    }


def archive(tmp_path: Path, *, drives: dict[str, dict[str, object]] | None = None) -> Path:
    """Write an archive of one node as the collection script does."""
    files = {
        "info.txt": "node: pve9\nlabel: \ncollected: 20261007T120000Z\n",
        "scan.json": json.dumps(scan()),
        "scan.json.exit": "0\n",
        "lsblk.json": json.dumps(lsblk()),
        "lsblk.json.exit": "0\n",
    }
    for device, drive in (drives or {"sda": sata(), "nvme0": nvme()}).items():
        files[f"smart/{device}.json"] = json.dumps(drive)
        files[f"smart/{device}.json.exit"] = "0\n"

    path = tmp_path / f"{TOP}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            member = tarfile.TarInfo(f"{TOP}/{name}")
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return path


def run(tmp_path: Path, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(tmp_path / "out"),
            "--prefix",
            "lab",
            "--origin",
            "A test",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_an_archive_becomes_an_anonymized_fixture(tmp_path: Path) -> None:
    result = run(tmp_path, archive(tmp_path))

    assert result.returncode == 0, result.stderr
    directory = tmp_path / "out" / "lab-pve9"
    assert sorted(path.name for path in directory.iterdir()) == [
        "lsblk.json",
        "nvme0.json",
        "recording.json",
        "scan.json",
        "sda.json",
    ]
    devices = json.loads((directory / "lsblk.json").read_text(encoding="utf-8"))["blockdevices"]
    assert devices[0]["serial"] == "ANON-SN-0002"
    assert devices[1]["wwn"] == "eui.0025380000000001"
    nvme0 = json.loads((directory / "nvme0.json").read_text(encoding="utf-8"))
    sda = json.loads((directory / "sda.json").read_text(encoding="utf-8"))
    # Numbered in the order of the scan (ADR 0023).
    assert nvme0["serial_number"] == "ANON-SN-0001"
    assert nvme0["nvme_namespaces"][0]["eui64"] == {"oui": 9528, "ext_id": 1}
    assert sda["serial_number"] == "ANON-SN-0002"
    assert sda["wwn"] == {"naa": 5, "oui": 9528, "id": 1}

    written = "".join(path.read_text(encoding="utf-8") for path in directory.iterdir())
    for serial in SERIALS:
        assert serial not in written


def test_the_recording_describes_every_file(tmp_path: Path) -> None:
    run(tmp_path, archive(tmp_path))

    recording = json.loads(
        (tmp_path / "out" / "lab-pve9" / "recording.json").read_text(encoding="utf-8")
    )

    assert recording["origin"] == "A test"
    assert recording["license"] == "AGPL-3.0-or-later"
    assert recording["node"] == "pve9"
    assert recording["smartmontools"] == "7.5"
    assert recording["files"][0] == {
        "file": "scan.json",
        "command": "smartctl --scan-open --json=c",
        "exit_status": 0,
    }
    assert recording["files"][-1] == {
        "file": "lsblk.json",
        "command": "lsblk -J -O",
        "exit_status": 0,
    }
    assert recording["files"][2] == {
        "file": "sda.json",
        "device": "/dev/sda",
        "type": "sat",
        "protocol": "ATA",
        "class": "ssd",
        "model": "Samsung SSD 850 EVO 250GB",
        "command": "smartctl -x --json=c -d sat /dev/sda",
        "exit_status": 0,
    }


def test_nothing_is_written_when_a_real_value_would_be_left(tmp_path: Path) -> None:
    # An EUI-64 where the anonymizer does not expect one: it fails closed.
    drive = nvme()
    drive["eui64"] = {"oui": 9528, "ext_id": 0x5B71B02A7F}

    result = run(tmp_path, archive(tmp_path, drives={"nvme0": drive}))

    assert result.returncode == 1
    assert "nvme0.json still contains a real value: EUI-64" in result.stderr
    assert not (tmp_path / "out").exists()


def test_the_archive_is_read_where_it_is(tmp_path: Path) -> None:
    path = archive(tmp_path)

    run(tmp_path, path)

    # Nothing is unpacked next to it.
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["out", path.name]


# The test data of other projects (ADR 0026)


def run_import(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "import",
            "--output",
            str(tmp_path / "out"),
            "--origin",
            "A test",
            "--repository",
            "https://example.org/project",
            "--commit",
            "0123abcd",
            "--copyright",
            "Copyright (c) 2026 Someone",
            "--license-file",
            str(license_text(tmp_path)),
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def license_text(tmp_path: Path) -> Path:
    path = tmp_path / "LICENSE.txt"
    path.write_text("MIT License\n", encoding="utf-8")
    return path


def sas() -> dict[str, object]:
    return {
        "smartctl": {"version": [7, 3], "argv": ["smartctl", "-a", "--json", "/dev/sdc"]},
        "device": {"name": "/dev/sdc", "type": "scsi", "protocol": "SCSI"},
        "scsi_model_name": "HGST HUSMR3280ASS200",
        "serial_number": "0HWZ3X1A",
        "logical_unit_id": "0x5000cca04eb1c2d4",
        "rotation_rate": 0,
    }


def written(tmp_path: Path, name: str, document: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_drive_of_another_project_becomes_a_fixture_without_a_scan(tmp_path: Path) -> None:
    source = written(tmp_path, "HGST.json", sas())

    result = run_import(tmp_path, "--license", "MIT", "--drive", f"sdc=tests/HGST.json:{source}")

    assert result.returncode == 0, result.stderr
    directory = tmp_path / "out"
    # No scan is made up where the source has none.
    assert sorted(path.name for path in directory.iterdir()) == ["recording.json", "sdc.json"]
    sdc = json.loads((directory / "sdc.json").read_text(encoding="utf-8"))
    assert sdc["serial_number"] == "ANON-SN-0001"
    assert sdc["logical_unit_id"] == "0x5000cca000000001"
    recording = json.loads((directory / "recording.json").read_text(encoding="utf-8"))
    assert recording["license"] == "MIT"
    assert recording["smartmontools"] == "7.3"
    assert recording["files"] == [
        {
            "file": "sdc.json",
            "device": "/dev/sdc",
            "type": "scsi",
            "protocol": "SCSI",
            "class": "ssd",
            "model": "HGST HUSMR3280ASS200",
            "command": "smartctl -a --json /dev/sdc",
            "exit_status": None,
        }
    ]
    assert recording["source"] == {
        "repository": "https://example.org/project",
        "commit": "0123abcd",
        "copyright": "Copyright (c) 2026 Someone",
        "license_file": (tmp_path / "LICENSE.txt").as_posix(),
        "paths": {"sdc.json": "tests/HGST.json"},
    }


def test_a_scan_alone_becomes_a_fixture(tmp_path: Path) -> None:
    source = written(tmp_path, "scan.json", scan())

    result = run_import(
        tmp_path, "--license", "Apache-2.0", "--scan", f"testdata/scan.json:{source}"
    )

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == [
        "recording.json",
        "scan.json",
    ]


def test_an_import_without_the_license_text_is_refused(tmp_path: Path) -> None:
    source = written(tmp_path, "HGST.json", sas())
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "import",
            "--output",
            str(tmp_path / "out"),
            "--origin",
            "A test",
            "--license",
            "MIT",
            "--repository",
            "https://example.org/project",
            "--commit",
            "0123abcd",
            "--copyright",
            "Copyright (c) 2026 Someone",
            "--license-file",
            str(tmp_path / "missing.txt"),
            "--drive",
            f"sdc=tests/HGST.json:{source}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "no license text at" in result.stderr
    assert not (tmp_path / "out").exists()


def test_what_the_source_changed_is_recorded(tmp_path: Path) -> None:
    source = written(tmp_path, "HGST.json", sas())

    run_import(
        tmp_path,
        "--license",
        "MIT",
        "--changes",
        "The source shortened the self-test log",
        "--drive",
        f"sdc=tests/HGST.json:{source}",
    )

    recording = json.loads((tmp_path / "out" / "recording.json").read_text(encoding="utf-8"))
    assert recording["source"]["changes"] == "The source shortened the self-test log"


def test_an_incompatible_license_is_refused(tmp_path: Path) -> None:
    source = written(tmp_path, "HGST.json", sas())

    result = run_import(
        tmp_path, "--license", "GPL-2.0-only", "--drive", f"sdc=tests/HGST.json:{source}"
    )

    assert result.returncode == 1
    assert "GPL-2.0-only is not a compatible license" in result.stderr
    assert not (tmp_path / "out").exists()


def test_an_import_that_would_leave_a_real_value_writes_nothing(tmp_path: Path) -> None:
    drive = sas()
    drive["logical_unit_id"] = "naa.5000cca04eb1c2d4"
    source = written(tmp_path, "HGST.json", drive)

    result = run_import(tmp_path, "--license", "MIT", "--drive", f"sdc=tests/HGST.json:{source}")

    assert result.returncode == 1
    assert "logical_unit_id in an unknown form" in result.stderr
    assert not (tmp_path / "out").exists()
