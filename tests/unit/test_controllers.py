# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the controllers whose drives smartctl cannot read (FR-109, ADR 0030).

Every test reads a sysfs tree in its temporary directory, never the /sys of
the machine it runs on (ADR 0016). The trees of the TrueNAS host and of the
cluster nodes are built from recordings; the trees with `mpi3mr` are
synthetic (tests/unit/hosts.py).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from frame import ScenarioHost
from hosts import (
    CLUSTER_NODE_SCSI_HOSTS,
    MIXED_SCSI_HOSTS,
    MPI3MR_SCSI_HOSTS,
    TRUENAS_SCSI_HOSTS,
    Host,
    write_scsi_hosts,
)

from pve_smart_alert import cli
from pve_smart_alert.config import Config
from pve_smart_alert.discovery import Discovery, discover
from pve_smart_alert.discovery.controllers import (
    UNSUPPORTED_DRIVERS,
    ScsiHost,
    Support,
    classify,
    read_scsi_hosts,
)
from pve_smart_alert.discovery.enrichment import MAX_DRIVER_NAME, HostPaths
from pve_smart_alert.doctor import Status, check_controllers
from pve_smart_alert.model import CheckKind, EventType, Severity
from pve_smart_alert.scan_report import render
from pve_smart_alert.tool_conditions import unsupported_controller

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "smartctl"


def paths_with(tmp_path: Path, drivers: dict[int, str]) -> HostPaths:
    sysfs = tmp_path / "sys"
    write_scsi_hosts(sysfs, drivers)
    return HostPaths(sysfs=sysfs)


# The classification


@pytest.mark.parametrize(
    ("driver", "support"),
    [
        ("mpi3mr", Support.UNSUPPORTED),
        # HBAs whose drives smartctl reads directly.
        ("mpt2sas", Support.DIRECT),
        ("mpt3sas", Support.DIRECT),
        # The enclosure management pseudo-host of AHCI.
        ("ahciem", Support.NOT_A_CONTROLLER),
        ("ahci", Support.NOT_REPORTED),
        ("megaraid_sas", Support.NOT_REPORTED),
        # Their drives are reached with explicit types: the HPE probe and
        # manual entries, not reported as unsupported (Research 04).
        ("hpsa", Support.NOT_REPORTED),
        ("smartpqi", Support.NOT_REPORTED),
        ("aacraid", Support.NOT_REPORTED),
        ("arcmsr", Support.NOT_REPORTED),
        # Unknown is not unsupported.
        ("usb-storage", Support.NOT_REPORTED),
        ("virtio_scsi", Support.NOT_REPORTED),
        ("some_new_driver", Support.NOT_REPORTED),
        (None, Support.NOT_REPORTED),
    ],
)
def test_each_driver_is_classified(driver: str | None, support: Support) -> None:
    assert classify(driver) is support


def test_every_unsupported_driver_names_its_source() -> None:
    assert set(UNSUPPORTED_DRIVERS) == {"mpi3mr"}
    for limitation in UNSUPPORTED_DRIVERS.values():
        assert limitation.reason
        assert limitation.source
        assert limitation.url.startswith("https://")


# Reading sysfs


def test_the_hosts_are_read_in_the_order_of_their_numbers(tmp_path: Path) -> None:
    paths = paths_with(tmp_path, {10: "ahci", 2: "mpt3sas", 0: "ahci"})
    # Not a SCSI host directory.
    (paths.sysfs / "class" / "scsi_host" / "power").mkdir()

    scsi = read_scsi_hosts(paths)

    assert scsi.error is None
    assert scsi.hosts == (ScsiHost(0, "ahci"), ScsiHost(2, "mpt3sas"), ScsiHost(10, "ahci"))


def test_a_missing_sysfs_is_no_host_and_no_error(tmp_path: Path) -> None:
    scsi = read_scsi_hosts(HostPaths(sysfs=tmp_path / "sys"))

    assert scsi.hosts == ()
    assert scsi.error is None
    assert scsi.unsupported == ()


def test_an_unreadable_sysfs_is_reported_and_no_host(tmp_path: Path) -> None:
    sysfs = tmp_path / "sys"
    (sysfs / "class").mkdir(parents=True)
    # Not a directory: listing it fails as an unreadable one would.
    (sysfs / "class" / "scsi_host").write_text("", encoding="utf-8")

    scsi = read_scsi_hosts(HostPaths(sysfs=sysfs))

    assert scsi.hosts == ()
    assert scsi.error is not None
    assert "scsi_host cannot be read" in scsi.error


def test_a_host_without_a_driver_is_not_reported(tmp_path: Path) -> None:
    sysfs = tmp_path / "sys"
    (sysfs / "class" / "scsi_host" / "host4").mkdir(parents=True)

    scsi = read_scsi_hosts(HostPaths(sysfs=sysfs))

    assert scsi.hosts == (ScsiHost(4, None),)
    assert scsi.unsupported == ()


def test_a_driver_name_from_sysfs_is_sanitized(tmp_path: Path) -> None:
    # Strings of the host are untrusted (ARCHITECTURE.md section 14).
    paths = paths_with(tmp_path, {0: "odd\x1b[31m\x07name" + "x" * 200})

    (host,) = read_scsi_hosts(paths).hosts

    assert host.driver is not None
    assert all(character >= " " for character in host.driver)
    assert len(host.driver) <= MAX_DRIVER_NAME
    assert host.support is Support.NOT_REPORTED


@pytest.mark.parametrize("drivers", [TRUENAS_SCSI_HOSTS, CLUSTER_NODE_SCSI_HOSTS])
def test_the_recorded_hosts_have_no_unsupported_controller(
    tmp_path: Path, drivers: dict[int, str]
) -> None:
    scsi = read_scsi_hosts(paths_with(tmp_path, drivers))

    assert len(scsi.hosts) == len(drivers)
    assert scsi.unsupported == ()


def test_an_mpi3mr_host_is_unsupported(tmp_path: Path) -> None:
    scsi = read_scsi_hosts(paths_with(tmp_path, MPI3MR_SCSI_HOSTS))

    assert scsi.unsupported == (ScsiHost(2, "mpi3mr"),)


def test_next_to_an_hba_only_the_mpi3mr_host_is_unsupported(tmp_path: Path) -> None:
    scsi = read_scsi_hosts(paths_with(tmp_path, MIXED_SCSI_HOSTS))

    assert scsi.unsupported == (ScsiHost(2, "mpi3mr"),)


def test_the_message_names_host_driver_and_the_upstream_limitation() -> None:
    text = ScsiHost(2, "mpi3mr").describe()

    assert text == (
        "SCSI host host2 has the driver mpi3mr: smartctl cannot read the drives behind it,"
        " so they are not monitored (upstream limitation, smartmontools issue 313)"
    )


# The tool condition


def test_no_unsupported_controller_is_no_condition() -> None:
    assert unsupported_controller(()) is None


def test_the_condition_names_every_unsupported_host() -> None:
    finding = unsupported_controller((ScsiHost(2, "mpi3mr"), ScsiHost(5, "mpi3mr")))

    assert finding is not None
    assert finding.check == "tool.unsupported_controller"
    assert finding.kind is CheckKind.CONDITION
    assert finding.severity is Severity.NOTICE
    assert "SCSI host host2 has the driver mpi3mr" in finding.text
    assert "SCSI host host5 has the driver mpi3mr" in finding.text


# Discovery and scan


def truenas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host(tmp_path, monkeypatch, FIXTURES / "hba" / "maintainer-truenas")


def test_discovery_reads_the_scsi_hosts_with_its_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = truenas(tmp_path, monkeypatch)
    host.scsi_hosts(TRUENAS_SCSI_HOSTS)

    discovery = host.discover()

    assert [scsi.driver for scsi in discovery.scsi_hosts.hosts] == [
        "mpt2sas",
        *["ahci"] * 6,
        "ahciem",
    ]
    assert discovery.scsi_hosts.unsupported == ()


def test_scan_of_the_truenas_host_names_no_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = truenas(tmp_path, monkeypatch)
    host.scsi_hosts(TRUENAS_SCSI_HOSTS)

    text = "\n".join(render(host.discover(), smartctl_path=Path("/usr/sbin/smartctl")))

    assert "Unsupported controller" not in text
    assert "mpt2sas" not in text
    assert "ahciem" not in text
    assert text.endswith("4 monitored, 0 in standby, 0 unreadable, 0 skipped")


def test_scan_names_an_mpi3mr_controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = truenas(tmp_path, monkeypatch)
    host.scsi_hosts(MIXED_SCSI_HOSTS)

    lines = render(host.discover(), smartctl_path=Path("/usr/sbin/smartctl"))

    assert lines[1] == (
        "Unsupported controller: SCSI host host2 has the driver mpi3mr: smartctl cannot read"
        " the drives behind it, so they are not monitored (upstream limitation,"
        " smartmontools issue 313)"
    )
    assert sum(line.startswith("Unsupported controller") for line in lines) == 1


# Doctor


@pytest.mark.parametrize(
    ("drivers", "detail"),
    [
        (
            TRUENAS_SCSI_HOSTS,
            "8 SCSI hosts (ahci, ahciem, mpt2sas), none whose drives smartctl cannot read",
        ),
        (
            CLUSTER_NODE_SCSI_HOSTS,
            "6 SCSI hosts (ahci), none whose drives smartctl cannot read",
        ),
        ({0: "ahci"}, "1 SCSI host (ahci), none whose drives smartctl cannot read"),
    ],
)
def test_doctor_reports_ok_for_the_recorded_hosts(
    tmp_path: Path, drivers: dict[int, str], detail: str
) -> None:
    result = check_controllers(paths_with(tmp_path, drivers))

    assert result.name == "controllers"
    assert result.status is Status.OK
    assert result.detail == detail
    assert result.advice is None


def test_doctor_without_a_scsi_host(tmp_path: Path) -> None:
    result = check_controllers(HostPaths(sysfs=tmp_path / "sys"))

    assert (result.status, result.detail) == (Status.OK, "no SCSI host")


def test_doctor_skips_when_sysfs_cannot_be_read(tmp_path: Path) -> None:
    sysfs = tmp_path / "sys"
    (sysfs / "class").mkdir(parents=True)
    (sysfs / "class" / "scsi_host").write_text("", encoding="utf-8")

    result = check_controllers(HostPaths(sysfs=sysfs))

    assert result.status is Status.SKIP
    assert "cannot be read" in result.detail


def test_doctor_warns_about_an_mpi3mr_controller(tmp_path: Path) -> None:
    result = check_controllers(paths_with(tmp_path, MIXED_SCSI_HOSTS))

    assert result.status is Status.WARN
    assert result.detail == ScsiHost(2, "mpi3mr").describe()
    assert result.advice is not None
    assert "https://github.com/smartmontools/smartmontools/issues/313" in result.advice
    assert "mpt3sas" not in result.detail


# A check run


def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScenarioHost:
    """A host of one healthy SATA SSD whose runs go through the command line."""
    host = ScenarioHost(tmp_path, monkeypatch, "pending-sectors")
    host.install()
    return host


def test_a_host_with_only_ahci_sends_nothing_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cluster nodes: their SCSI hosts are AHCI ports only.
    host = installed(tmp_path, monkeypatch)
    host.scsi_hosts(CLUSTER_NODE_SCSI_HOSTS)

    (first,) = host.run("01-healthy")
    assert first.event is EventType.FIRST_RUN
    assert "unsupported controller" not in first.body.lower()
    assert host.run("02-healthy") == []
    assert host.run("02-healthy", advance=timedelta(days=2)) == []


def test_an_mpi3mr_controller_raises_the_condition_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = installed(tmp_path, monkeypatch)
    host.scsi_hosts(TRUENAS_SCSI_HOSTS)
    assert len(host.run("01-healthy")) == 1

    host.scsi_host(8, "mpi3mr")
    (problem,) = host.run("02-healthy")

    assert problem.event is EventType.TOOL
    assert problem.severity is Severity.NOTICE
    assert problem.subject == (
        "[pve-smart-alert] NOTICE pve1: pve-smart-alert: unsupported controller"
    )
    assert "tool.unsupported_controller" in problem.body
    assert "host8" in problem.body
    assert "mpi3mr" in problem.body
    assert "smartmontools issue 313" in problem.body
    assert "mpt2sas" not in problem.body
    assert host.run("02-healthy") == []

    # The controller is gone: recovered after the runs of the policy, like
    # every condition (FR-518).
    host.remove_scsi_host(8)
    assert host.run("02-healthy") == []
    (recovered,) = host.run("02-healthy")

    assert recovered.event is EventType.TOOL
    assert recovered.severity is Severity.INFO
    assert (
        recovered.subject == "[pve-smart-alert] INFO pve1: pve-smart-alert: recovered: controller"
    )
    assert "RECOVERED tool.unsupported_controller" in recovered.body
    assert host.run("02-healthy") == []
    assert host.exit_status == 0


def test_the_first_run_names_an_mpi3mr_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = installed(tmp_path, monkeypatch)
    host.scsi_hosts(MPI3MR_SCSI_HOSTS)

    (first,) = host.run("01-healthy")

    assert first.event is EventType.FIRST_RUN
    assert "tool.unsupported_controller" in first.body
    assert "host2" in first.body
    assert host.run("02-healthy") == []


def test_the_scan_command_names_the_controller_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A notice, not a failure of the command: the scan itself worked.
    host = truenas(tmp_path, monkeypatch)
    host.scsi_hosts(MPI3MR_SCSI_HOSTS)
    monkeypatch.setattr(cli, "load_config", host.config)

    def discover_here(config: Config, **keywords: object) -> Discovery:
        return discover(config, runner=host, paths=host.paths, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "discover", discover_here)

    assert cli.main(["scan"]) == cli.EXIT_OK
    assert "Unsupported controller: SCSI host host2 has the driver mpi3mr" in (
        capsys.readouterr().out
    )
