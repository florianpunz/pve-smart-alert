# SPDX-License-Identifier: AGPL-3.0-or-later
"""A host for the tests of discovery, scan and dump-fixture (ADR 0016).

The fake smartctl runs as a real program and replays a recording; lsblk is
answered from the same recording. Changes for one case are made on a copy.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from pve_smart_alert.config import (
    Config,
    DiscoverySettings,
    DriveOverride,
    SmartctlSettings,
)
from pve_smart_alert.discovery import Discovery, HostPaths, discover
from pve_smart_alert.process import ProcessResult, run_with_timeout

TESTS: Final = Path(__file__).resolve().parent.parent
FAKE: Final = TESTS / "fake-smartctl"
RECORDINGS: Final = TESTS / "fixtures" / "smartctl" / "direct"
LSBLK: Final = Path("/test/lsblk")


class Host:
    """A host made of a copy of one recording: smartctl is the fake, lsblk the record."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path) -> None:
        self.recording = tmp_path / "recording"
        shutil.copytree(source, self.recording)
        self.paths = HostPaths(lsblk=LSBLK, disk_links=tmp_path / "disk", sysfs=tmp_path / "sys")
        self.log = tmp_path / "calls.log"
        self.lsblk_fails = False
        monkeypatch.setenv("FAKE_SMARTCTL_RECORDING", str(self.recording))
        monkeypatch.setenv("FAKE_SMARTCTL_LOG", str(self.log))

    @classmethod
    def of_node(
        cls,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        node: str,
        *,
        prefix: str = "test-cluster",
    ) -> Host:
        """A host made of the anonymized recording of one node; by default of the test cluster."""
        return cls(tmp_path, monkeypatch, RECORDINGS / f"{prefix}-{node}")

    @classmethod
    def of_recording(cls, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> Host:
        """A host made of one named recording, such as the failing-hdd scenario."""
        return cls(tmp_path, monkeypatch, RECORDINGS / name)

    def __call__(
        self, command: Sequence[str | Path], *, input_text: str | None = None, timeout: float
    ) -> ProcessResult:
        if str(command[0]) == str(LSBLK):
            if self.lsblk_fails:
                return ProcessResult(returncode=1, stdout="", stderr="", timed_out=False)
            # A recording of another project has no lsblk: a host without
            # block devices then, which lsblk answers with an empty list.
            path = self.recording / "lsblk.json"
            stdout = path.read_text(encoding="utf-8") if path.exists() else '{"blockdevices": []}'
            return ProcessResult(returncode=0, stdout=stdout, stderr="", timed_out=False)
        return run_with_timeout(command, input_text=input_text, timeout=timeout)

    def config(self, *, drives: tuple[DriveOverride, ...] = (), **discovery: object) -> Config:
        return Config(
            smartctl=SmartctlSettings(path=FAKE, timeout_seconds=10.0),
            discovery=DiscoverySettings(**discovery),  # type: ignore[arg-type]
            drives=drives,
        )

    def discover(self, *, drives: tuple[DriveOverride, ...] = (), **discovery: object) -> Discovery:
        return discover(self.config(drives=drives, **discovery), runner=self, paths=self.paths)

    def read_devices(self) -> list[str]:
        """Return the devices smartctl was asked for, the scans left out."""
        if not self.log.exists():
            return []
        calls = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [call[-1] for call in calls if "--scan-open" not in call and "--scan" not in call]

    def behave(self, file: str, **behavior: object) -> None:
        """Make the fake smartctl answer differently for one file."""
        path = self.recording / "behavior.json"
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        current[file] = behavior
        path.write_text(json.dumps(current), encoding="utf-8")

    def add_file(self, file: str, document: object, *, device: str, device_type: str) -> None:
        """Add a drive output to the recording, as reached through `device`."""
        (self.recording / file).write_text(json.dumps(document), encoding="utf-8")
        recording = json.loads((self.recording / "recording.json").read_text(encoding="utf-8"))
        recording["files"].append(
            {"file": file, "device": device, "type": device_type, "exit_status": 0}
        )
        (self.recording / "recording.json").write_text(json.dumps(recording), encoding="utf-8")

    def set_scan(self, *devices: dict[str, object]) -> None:
        """Make the device scan list these devices, also for a recording without a scan."""
        scan = {
            "json_format_version": [1, 0],
            "smartctl": {"version": [7, 5], "argv": ["smartctl", "--scan-open", "--json=c"]},
            "devices": list(devices),
        }
        (self.recording / "scan.json").write_text(json.dumps(scan), encoding="utf-8")
        recording = json.loads((self.recording / "recording.json").read_text(encoding="utf-8"))
        files = [entry for entry in recording["files"] if entry["file"] != "scan.json"]
        recording["files"] = [{"file": "scan.json", "exit_status": 0}, *files]
        (self.recording / "recording.json").write_text(json.dumps(recording), encoding="utf-8")

    def scsi_host(self, number: int, driver: str) -> None:
        """Give the host a SCSI host with this driver in its sysfs."""
        path = self.paths.sysfs / "class" / "scsi_host" / f"host{number}" / "proc_name"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{driver}\n", encoding="utf-8")

    def drive(self, file: str) -> dict[str, object]:
        loaded: dict[str, object] = json.loads((self.recording / file).read_text("utf-8"))
        return loaded

    def change_lsblk(self, name: str, **values: object) -> None:
        path = self.recording / "lsblk.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        for device in document["blockdevices"]:
            if device["name"] == name:
                device.update(values)
                break
        else:
            document["blockdevices"].append({"name": name, "kname": name, **values})
        path.write_text(json.dumps(document), encoding="utf-8")


# A host with identifiers in the form of real ones, made up for the tests.
REAL_SERIALS: Final = ("S2R5NX0H123456A", "S35ENX0J654321")
REAL_WWN: Final = "5002538e40a1b2c3"
REAL_EUI: Final = "0025385b71b02a7f"
REAL_UUID: Final = "4f8c2c1e-0b3a-4b6e-9d2f-1c0a5e7b9d31"


def write_real_looking_recording(directory: Path) -> None:
    """Write a recording of a host with an ATA and an NVMe drive and real-looking identifiers."""
    directory.mkdir(parents=True)
    smartctl = {"version": [7, 5]}
    scan = {
        "json_format_version": [1, 0],
        "smartctl": {**smartctl, "argv": ["smartctl", "--scan-open", "--json=c"]},
        "devices": [
            {"name": "/dev/sda", "info_name": "/dev/sda [SAT]", "type": "sat", "protocol": "ATA"},
            {"name": "/dev/nvme0", "info_name": "/dev/nvme0", "type": "nvme", "protocol": "NVMe"},
        ],
    }
    sata = {
        "json_format_version": [1, 0],
        "smartctl": {**smartctl, "argv": ["smartctl", "-x", "--json=c", "-d", "sat", "/dev/sda"]},
        "device": {"name": "/dev/sda", "type": "sat", "protocol": "ATA"},
        "model_name": "Samsung SSD 850 EVO 250GB",
        "serial_number": REAL_SERIALS[0],
        "wwn": {"naa": 5, "oui": 9528, "id": 0xE40A1B2C3},
        "rotation_rate": 0,
        "smart_support": {"available": True, "enabled": True},
        "endurance_used": {"current_percent": 12},
    }
    nvme = {
        "json_format_version": [1, 0],
        "smartctl": {
            **smartctl,
            "argv": ["smartctl", "-x", "--json=c", "-d", "nvme", "/dev/nvme0"],
        },
        "device": {"name": "/dev/nvme0", "type": "nvme", "protocol": "NVMe"},
        "model_name": "SAMSUNG MZVLW256HEHP-000L2",
        "serial_number": REAL_SERIALS[1],
        "nvme_namespaces": [{"id": 1, "eui64": {"oui": 9528, "ext_id": 0x5B71B02A7F}}],
        "nvme_smart_health_information_log": {"percentage_used": 2, "critical_warning": 0},
    }
    lsblk = {
        "blockdevices": [
            {
                "name": "sda",
                "kname": "sda",
                "type": "disk",
                "tran": "sata",
                "serial": REAL_SERIALS[0],
                "wwn": f"0x{REAL_WWN}",
                "ptuuid": REAL_UUID,
                "children": [
                    {
                        "name": "sda3",
                        "kname": "sda3",
                        "type": "part",
                        "fstype": "LVM2_member",
                        "children": [{"name": "pve-root", "kname": "dm-0", "type": "lvm"}],
                    }
                ],
            },
            {
                "name": "nvme0n1",
                "kname": "nvme0n1",
                "type": "disk",
                "tran": "nvme",
                "serial": REAL_SERIALS[1],
                "wwn": f"eui.{REAL_EUI}",
            },
        ]
    }
    files = {"scan.json": scan, "sda.json": sata, "nvme0.json": nvme, "lsblk.json": lsblk}
    for name, document in files.items():
        (directory / name).write_text(json.dumps(document), encoding="utf-8")
    recording = {
        "files": [
            {"file": "scan.json", "exit_status": 0},
            {"file": "sda.json", "device": "/dev/sda", "type": "sat", "exit_status": 0},
            {"file": "nvme0.json", "device": "/dev/nvme0", "type": "nvme", "exit_status": 0},
        ]
    }
    (directory / "recording.json").write_text(json.dumps(recording), encoding="utf-8")


REAL_VALUES: Final = (*REAL_SERIALS, REAL_WWN, REAL_EUI, REAL_UUID, str(0xE40A1B2C3))
