# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for `check --dry-run` and `config` (FR-601, FR-405, FR-407).

The dry run runs against the anonymized recordings of the fake smartctl
(ADR 0016): the failing hard disk of the derived recording, and the healthy
drives of the test cluster. The state directory is a temporary one, so the
last good configuration is written and read there.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hosts import FAKE, Host

from pve_smart_alert import cli
from pve_smart_alert import config as config_module
from pve_smart_alert.config import Config
from pve_smart_alert.discovery import discover


def fake_smartctl_config(content: str = "") -> str:
    """Return a configuration file that reads the drives with the fake smartctl."""
    return f'[smartctl]\npath = "{FAKE}"\n{content}'


FAILING_HDD_FINDINGS = {
    "health.failed": "critical",
    "selftest.failed": "warning",
    "temperature": "critical",
    "ata.attribute_failing": "critical",
    "ata.reallocated_sectors": "critical",
    "ata.reported_uncorrectable": "critical",
    "ata.command_timeouts": "warning",
    "ata.pending_sectors": "critical",
    "ata.offline_uncorrectable": "critical",
    "ata.spin_retries": "warning",
    "ata.end_to_end_errors": "warning",
}


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point the command-line interface at a temporary configuration and state directory."""
    config = tmp_path / "config.toml"
    last_good = tmp_path / "last-good-config.json"
    # The loader reads the path from its own module, the commands from theirs.
    monkeypatch.setattr(config_module, "CONFIG_PATH", config)
    monkeypatch.setattr(cli, "CONFIG_PATH", config)
    monkeypatch.setattr(cli, "LAST_GOOD_CONFIG_PATH", last_good)
    return config, last_good


def with_host(monkeypatch: pytest.MonkeyPatch, host: Host) -> None:
    """Have the commands of the interface discover through the host of a recording."""
    real_discover = discover

    def discover_on_host(config: Config, **kwargs: object) -> object:
        return real_discover(config, **kwargs, runner=host, paths=host.paths)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "discover", discover_on_host)


# check --dry-run


def test_the_dry_run_shows_the_findings_of_a_failing_drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    paths: tuple[Path, Path],
) -> None:
    config_path, _ = paths
    host = Host.of_recording(tmp_path, monkeypatch, "failing-hdd")
    with_host(monkeypatch, host)
    config_path.write_text(fake_smartctl_config(), encoding="utf-8")

    assert cli.main(["check", "--dry-run"]) == cli.EXIT_PROBLEM

    out = capsys.readouterr().out
    assert "/dev/sda [sat] Samsung HD502HI, serial ANON-SN-0001" in out
    for line in out.splitlines():
        if line.startswith("  "):
            check, severity = line.split()[0], line.split()[1]
            assert severity == FAILING_HDD_FINDINGS[check]
    # The events stay silent without a baseline, and the wear check does not
    # apply to a hard disk.
    assert "ata.crc_errors" not in out
    assert "ata.error_log" not in out
    assert "wear" not in out
    assert "11 findings" in out


@pytest.mark.parametrize("node", ["pve5", "pve6", "pve7"])
def test_the_dry_run_of_healthy_drives_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    paths: tuple[Path, Path],
    node: str,
) -> None:
    # The review of the provisional default thresholds against all recordings
    # of the test cluster (ROADMAP.md, milestone M3): the healthy drives of
    # every node stay below every threshold.
    config_path, _ = paths
    host = Host.of_node(tmp_path, monkeypatch, node)
    with_host(monkeypatch, host)
    config_path.write_text(fake_smartctl_config(), encoding="utf-8")

    assert cli.main(["check", "--dry-run"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "monitored" in out
    assert "no findings" in out


def test_the_dry_run_uses_the_last_good_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    paths: tuple[Path, Path],
) -> None:
    # Acceptance step 4 of M3: a typing error changes nothing, the run goes
    # on with the last good configuration (FR-406).
    config_path, _ = paths
    host = Host.of_recording(tmp_path, monkeypatch, "failing-hdd")
    with_host(monkeypatch, host)
    config_path.write_text(fake_smartctl_config(), encoding="utf-8")
    cli.main(["config", "check"])  # saves the last good configuration
    capsys.readouterr()
    config_path.write_text(
        fake_smartctl_config('[checks."no_such_check"]\nenabled = false\n'),
        encoding="utf-8",
    )

    code = cli.main(["check", "--dry-run"])

    # The findings come from the last good configuration, and the error is
    # named on standard error.
    assert code == cli.EXIT_PROBLEM
    error = capsys.readouterr().err
    assert 'unknown check "no_such_check"' in error
    assert "the last good configuration is in use" in error


def test_check_without_dry_run_is_not_built_yet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["check"])

    assert exit_info.value.code == 2
    assert "check needs --dry-run" in capsys.readouterr().err


# config check


def test_config_check_reports_a_valid_file(
    capsys: pytest.CaptureFixture[str], paths: tuple[Path, Path]
) -> None:
    config_path, _ = paths
    config_path.write_text('[checks."wear"]\nwarning = 90\n', encoding="utf-8")

    assert cli.main(["config", "check"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert f"{config_path}: valid" in out


def test_config_check_names_the_key_of_an_error(
    capsys: pytest.CaptureFixture[str], paths: tuple[Path, Path]
) -> None:
    config_path, _ = paths
    config_path.write_text("[notify]\ntimeout = 30\n", encoding="utf-8")

    assert cli.main(["config", "check"]) == cli.EXIT_PROBLEM

    out = capsys.readouterr().out
    assert f"{config_path}:" in out
    assert 'unknown key "timeout" in section [notify] (line 2)' in out


def test_config_check_saves_the_last_good_configuration(
    paths: tuple[Path, Path],
) -> None:
    config_path, last_good = paths
    config_path.write_text('[checks."wear"]\nwarning = 90\n', encoding="utf-8")

    cli.main(["config", "check"])

    assert last_good.exists()


# config show


def test_config_show_names_the_origin_of_each_value(
    capsys: pytest.CaptureFixture[str], paths: tuple[Path, Path]
) -> None:
    config_path, _ = paths
    config_path.write_text(
        '[checks."ata.reallocated_sectors"]\nwarning = 3\n'
        '[checks."temperature"]\nwarning = { hdd = 48 }\n',
        encoding="utf-8",
    )

    assert cli.main(["config", "show"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert 'transport = "auto"' in out
    assert "(default)" in out
    assert (
        '"ata.reallocated_sectors"  enabled = true (default), notice = 1 (default),'
        " warning = 3 (file), critical = 70 (default)"
    ) in out
    # The classes that keep their default are named with it.
    assert "warning = hdd 48, ssd 60, nvme 70 (file)" in out
    assert "[[drive]]  none" in out


def test_config_show_defaults_prints_the_built_in_defaults(
    capsys: pytest.CaptureFixture[str], paths: tuple[Path, Path]
) -> None:
    config_path, _ = paths
    config_path.write_text('[checks."wear"]\nwarning = 90\n', encoding="utf-8")

    assert cli.main(["config", "show", "--defaults"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "the built-in defaults apply" in out
    assert "warning = 90" not in out
    assert '"wear"  enabled = true (default), notice = 80 (default), warning = 95 (default)' in out


def test_config_show_works_with_an_invalid_file(
    capsys: pytest.CaptureFixture[str], paths: tuple[Path, Path]
) -> None:
    # The last good configuration is shown, and the error with it (FR-406).
    config_path, _ = paths
    config_path.write_text('[notify]\ntransport = "mail"\n', encoding="utf-8")
    cli.main(["config", "check"])
    capsys.readouterr()
    config_path.write_text("[notify]\ntimeout = 30\n", encoding="utf-8")

    assert cli.main(["config", "show"]) == cli.EXIT_OK

    captured = capsys.readouterr()
    assert "unknown key" in captured.err
    assert 'transport = "mail"' in captured.out


def test_a_threshold_changed_in_the_configuration_changes_the_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    paths: tuple[Path, Path],
) -> None:
    # Acceptance step 3 of M3: a threshold changed in the configuration
    # changes the result.
    config_path, _ = paths
    config_path.write_text(
        fake_smartctl_config('[checks."ata.command_timeouts"]\nwarning = 1000\n'),
        encoding="utf-8",
    )
    host = Host.of_recording(tmp_path, monkeypatch, "failing-hdd")
    with_host(monkeypatch, host)

    assert cli.main(["check", "--dry-run"]) == cli.EXIT_PROBLEM

    out = capsys.readouterr().out
    # The 600 decoded command timeouts of the recording are under the new
    # threshold; the check has no critical severity.
    assert "ata.command_timeouts" not in out
    assert "ata.reallocated_sectors" in out


def test_a_per_drive_override_removes_one_finding_of_that_drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    paths: tuple[Path, Path],
) -> None:
    # Acceptance step 3 of M3: an override that disables a check removes
    # that finding for that drive.
    config_path, _ = paths
    config_path.write_text(
        fake_smartctl_config(
            '[[drive]]\nserial = "ANON-SN-0001"\n\n[drive.checks."ata.reallocated_sectors"]\n'
            "enabled = false\n"
        ),
        encoding="utf-8",
    )
    host = Host.of_recording(tmp_path, monkeypatch, "failing-hdd")
    with_host(monkeypatch, host)

    assert cli.main(["check", "--dry-run"]) == cli.EXIT_PROBLEM

    out = capsys.readouterr().out
    assert "ata.reallocated_sectors" not in out
    # The findings of the checks that stay enabled are still there.
    assert "ata.pending_sectors" in out
