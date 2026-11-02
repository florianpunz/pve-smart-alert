# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for `pve-smart-alert scan` (FR-108).

The report is checked against the anonymized recordings of the test
cluster, which is what acceptance steps 1, 2 and 4 of M2 look at on the
real nodes.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from hosts import Host

from pve_smart_alert import cli
from pve_smart_alert.config import Config, ConfigError, DriveSelector, ManualDevice, SelectorKind
from pve_smart_alert.discovery import Discovery, discover
from pve_smart_alert.scan_report import render
from scenarios import SCENARIOS, build

SMARTCTL = Path("/usr/sbin/smartctl")


def report(discovery: Discovery) -> str:
    return "\n".join(render(discovery, smartctl_path=SMARTCTL)) + "\n"


def test_a_drive_is_shown_with_what_the_tool_knows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    discovery = Host.of_node(tmp_path, monkeypatch, "pve7").discover()

    text = report(discovery)

    assert text.startswith("smartctl 7.5 at /usr/sbin/smartctl\n\n")
    block = text.split("\n\n")[1]
    lines = block.splitlines()
    assert lines[0] == "/dev/sda [sat], from the scan: monitored"
    assert lines[1:9] == [
        "  Model:     Samsung SSD 850 EVO 250GB",
        "  Serial:    ANON-SN-0001",
        "  WWN:       5002538000000001",
        "  Firmware:  EMT01B6Q",
        "  Capacity:  250.06 GB",
        "  Class:     ssd, transport sata",
        "  Used by:   LVM volume group pve",
        "  Wear:      12 % (vendor attribute)",
    ]
    assert lines[9].startswith("  Read in:   ")
    assert text.endswith("\n3 monitored, 0 in standby, 0 unreadable, 0 skipped\n")


def test_the_nvme_drives_show_their_volume_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = report(Host.of_node(tmp_path, monkeypatch, "pve7").discover())

    assert "/dev/nvme0 [nvme], from the scan: monitored" in text
    assert "  Used by:   LVM volume group pm961-b\n" in text
    assert "  Used by:   LVM volume group pm961-a\n" in text
    assert "  Wear:      19 % (endurance_used)\n" in text


def test_a_wear_value_that_differs_from_the_web_interface_names_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Acceptance step 2 of M2: the Fanxiang S301 on pve5 (ADR 0021).
    text = report(Host.of_node(tmp_path, monkeypatch, "pve5").discover())

    assert "  Wear:      44 % (endurance_used), the web interface shows 0 %\n" in text


def test_the_intenso_ssd_names_its_source_without_the_web_interface_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The standalone host pve1: 3 % against 0 % in the web interface, less than 10 points apart.
    text = report(Host.of_node(tmp_path, monkeypatch, "pve1", prefix="standalone").discover())

    assert "  Wear:      3 % (endurance_used)\n" in text
    assert "the web interface shows" not in text
    assert "/dev/sdb" not in text


def test_a_small_difference_names_only_the_value_of_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host.of_node(tmp_path, monkeypatch, "pve1", prefix="standalone")
    drive = host.drive("sda.json")
    drive["endurance_used"] = {"current_percent": 7}
    statistics = drive["ata_device_statistics"]
    assert isinstance(statistics, dict)
    for page in statistics["pages"]:
        assert isinstance(page, dict)
        for entry in page["table"]:
            assert isinstance(entry, dict)
            if entry["name"] == "Percentage Used Endurance Indicator":
                entry["value"] = 7
    host.behave("sda.json", stdout=json.dumps(drive), exit_status=0)

    text = report(host.discover())

    # 7 against 0 in the web interface: less than 10 points apart.
    assert "  Wear:      7 % (endurance_used)\n" in text
    assert "the web interface shows" not in text


def test_an_unreadable_manual_device_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Acceptance step 4 of M2.
    discovery = Host.of_node(tmp_path, monkeypatch, "pve7").discover(
        devices=(ManualDevice("/dev/sdz", "sat"),)
    )

    text = report(discovery)

    assert (
        "/dev/sdz [sat], manual entry: unreadable\n"
        "  Reason:    Smartctl open device: /dev/sdz failed: No such device\n"
    ) in text
    assert text.endswith("\n3 monitored, 0 in standby, 1 unreadable, 0 skipped\n")


def test_skipped_and_sleeping_devices_name_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host.of_node(tmp_path, monkeypatch, "pve7")
    host.behave("sda.json", standby="STANDBY")
    rule = DriveSelector(SelectorKind.MODEL, "SAMSUNG MZVLW256HEHP-000H1")

    text = report(host.discover(exclude=(rule,)))

    assert "/dev/sda [sat], from the scan: in standby (STANDBY), not woken\n" in text
    assert (
        '/dev/nvme1 [nvme], from the scan: skipped, excluded (model = "SAMSUNG MZVLW256HEHP-000H1")'
    ) in text
    assert text.endswith("\n1 monitored, 1 in standby, 0 unreadable, 1 skipped\n")


def test_a_failed_scan_and_a_missing_lsblk_are_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host.of_node(tmp_path, monkeypatch, "pve7")
    host.behave("scan.json", stdout="not json", exit_status=0)
    host.lsblk_fails = True

    lines = render(host.discover(), smartctl_path=SMARTCTL)

    assert lines[:3] == [
        "smartctl at /usr/sbin/smartctl, version not known",
        "Device scan failed: the device scan answered without valid JSON",
        "Without lsblk: lsblk did not answer; transport, links and use are missing",
    ]


# The command


def install(monkeypatch: pytest.MonkeyPatch, host: Host, config: Config | None = None) -> None:
    """Let the command see this host and this configuration."""
    chosen = config if config is not None else host.config()
    monkeypatch.setattr(cli, "load_config", lambda: chosen)

    def discover_here(config: Config, **keywords: object) -> Discovery:
        return discover(config, runner=host, paths=host.paths, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "discover", discover_here)


def test_the_command_prints_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, Host.of_node(tmp_path, monkeypatch, "pve6"))
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    assert cli.main(["scan"]) == cli.EXIT_OK

    captured = capsys.readouterr()
    assert "/dev/nvme0 [nvme], from the scan: monitored" in captured.out
    assert "  Used by:   LVM volume group vg_data\n" in captured.out
    # Progress goes to standard error, so that the report stays clean.
    assert "reading /dev/sda [sat] ...\n" in captured.err


def test_without_a_terminal_there_is_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A run of the timer logs one summary line, not one line per drive (FR-606).
    install(monkeypatch, Host.of_node(tmp_path, monkeypatch, "pve6"))
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)

    cli.main(["scan"])

    assert "reading" not in capsys.readouterr().err


def test_a_failed_scan_ends_with_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    host = Host.of_node(tmp_path, monkeypatch, "pve6")
    host.behave("scan.json", stdout="not json", exit_status=0)
    install(monkeypatch, host)

    assert cli.main(["scan"]) == cli.EXIT_PROBLEM
    assert "Device scan failed" in capsys.readouterr().out


def test_an_unusable_configuration_ends_with_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> Config:
        raise ConfigError('unknown key "exclud" in section [discovery]')

    monkeypatch.setattr(cli, "load_config", broken)

    assert cli.main(["scan"]) == cli.EXIT_USAGE
    assert "unknown key" in capsys.readouterr().err


def test_a_sas_drive_behind_an_hba_is_shown_with_its_endurance_indicator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The maintainer's TrueNAS host: SAS SSDs behind an LSI SAS2308 HBA.
    source = Path(__file__).resolve().parent.parent / "fixtures" / "smartctl" / "hba"
    text = report(Host(tmp_path, monkeypatch, source / "maintainer-truenas").discover())

    block = next(part for part in text.split("\n\n") if part.startswith("/dev/sda "))
    assert block.splitlines()[0] == "/dev/sda [scsi], from the scan: monitored"
    assert "  WWN:       5000c50000000001" in block
    assert "  Class:     ssd, transport sas" in block
    assert "  Wear:      0 % (endurance indicator)" in block
    assert text.endswith("\n4 monitored, 0 in standby, 0 unreadable, 0 skipped\n")


def test_drives_behind_megaraid_show_controller_and_device_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Result 2 of M6 on the MegaRAID scenario: the physical drives behind
    # the controller, and the logical volume skipped with a reason
    # (ADR 0028).
    steps = build(SCENARIOS["megaraid-degraded"], tmp_path / "steps")
    host = Host(tmp_path, monkeypatch, steps[0])
    host.scsi_host(6, "megaraid_sas")

    blocks = report(host.discover()).split("\n\n")

    assert blocks[1].splitlines() == [
        "/dev/sda [scsi], from the scan: skipped, logical-volume"
        " (lsblk vendor DELL, model PERC H730P Mini)",
        "  Reason:    lsblk vendor DELL, model PERC H730P Mini",
    ]
    assert blocks[2].startswith("/dev/bus/6 [sat+megaraid,14], from the scan: monitored\n")
    assert "\n  Location:  /dev/bus/6 (megaraid_sas), device 14\n" in blocks[2]
    assert blocks[3].startswith("/dev/bus/6 [megaraid,8], from the scan: monitored\n")
    assert "\n  Location:  /dev/bus/6 (megaraid_sas), device 8\n" in blocks[3]
    assert blocks[-1] == "2 monitored, 0 in standby, 0 unreadable, 1 skipped\n"


def test_a_drive_without_a_controller_has_no_location_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = report(Host.of_node(tmp_path, monkeypatch, "pve7").discover())

    assert "Location:" not in text


def test_a_drive_whose_model_holds_an_unprinted_character_gets_a_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `scan` prints the model with the character replaced by a space, and a
    # selector compares the stored value. The line `Selector:` is the value
    # as it is written into the configuration (ADR 0036).
    host = Host.of_node(tmp_path, monkeypatch, "pve7")
    recording = json.loads((host.recording / "recording.json").read_text(encoding="utf-8"))
    entry = next(item for item in recording["files"] if item.get("device"))
    path = host.recording / entry["file"]
    drive = json.loads(path.read_text(encoding="utf-8"))
    drive["model_name"] = "ACME\x01X 8TB"
    path.write_text(json.dumps(drive), encoding="utf-8")

    discovery = host.discover()

    (line,) = [line for line in report(discovery).splitlines() if "Selector:" in line]
    selector = tomllib.loads(line.split("Selector:", 1)[1].strip())
    identity = next(
        found.snapshot.identity
        for found in discovery.devices
        if found.snapshot is not None and found.candidate.name == entry["device"]
    )
    assert DriveSelector(SelectorKind.MODEL, selector["model"]).matches(identity)


def test_a_long_value_gets_a_selector_line_that_is_still_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A value longer than the printed limit cannot be printed whole. The
    # selector line cuts it and carries the mark, but stays a TOML string:
    # cutting the escaped line itself left half a string that nobody can
    # paste (ADR 0036).
    host = Host.of_node(tmp_path, monkeypatch, "pve7")
    recording = json.loads((host.recording / "recording.json").read_text(encoding="utf-8"))
    entry = next(item for item in recording["files"] if item.get("device"))
    path = host.recording / entry["file"]
    drive = json.loads(path.read_text(encoding="utf-8"))
    drive["model_name"] = "ACME-" + "X" * 300
    path.write_text(json.dumps(drive), encoding="utf-8")

    (line,) = [line for line in report(host.discover()).splitlines() if "Selector:" in line]
    selector = tomllib.loads(line.split("Selector:", 1)[1].strip())

    assert selector["model"].endswith("…")
    assert len(selector["model"]) == 201
