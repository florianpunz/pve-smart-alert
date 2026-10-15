# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of the systemd units and how the package installs them (ADR 0006).

The units are read as text: what systemd makes of them is checked by
`systemd-analyze verify` in the package job of CI, and what they do on a host
by the package test in a container. These tests hold the values that the
decision records and the code of the tool depend on.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

from pve_smart_alert.cli import EXIT_LOCKED
from pve_smart_alert.paths import RUN_DIR, STATE_DIR, TIMER_UNIT

REPOSITORY = Path(__file__).resolve().parents[2]
UNITS = REPOSITORY / "systemd"
SERVICE = "pve-smart-alert.service"
FAILURE = "pve-smart-alert-failure.service"

# Options that sandbox a run.
SANDBOXING = re.compile(
    r"^(Protect\w+|Private\w+|NoNewPrivileges|Restrict\w+|ReadOnlyPaths|ReadWritePaths"
    r"|InaccessiblePaths|CapabilityBoundingSet|AmbientCapabilities|SystemCallFilter"
    r"|SystemCallArchitectures|LockPersonality|MemoryDenyWriteExecute|DynamicUser|User|Group)$"
)

# The sandboxing of the check service that was tested on a real host (ADR 0025).
DECIDED_SANDBOXING = {
    "PrivateTmp": "yes",
    "ProtectSystem": "full",
    "ProtectHome": "read-only",
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectKernelLogs": "yes",
    "ProtectControlGroups": "yes",
    "ProtectClock": "yes",
    "ProtectHostname": "yes",
    "RestrictRealtime": "yes",
    "RestrictSUIDSGID": "yes",
    "LockPersonality": "yes",
    "RestrictNamespaces": "yes",
    "SystemCallArchitectures": "native",
    "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6 AF_NETLINK",
    "NoNewPrivileges": "yes",
}


def read_unit(name: str) -> configparser.ConfigParser:
    """Return a unit file as sections and keys, with the case of the keys kept."""
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string((UNITS / name).read_text(encoding="utf-8"), source=name)
    return parser


def installed(source: str) -> str | None:
    """Return the directory the install list puts a file of the repository in."""
    for line in (REPOSITORY / "debian" / "pve-smart-alert.install").read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == source:
            return "/" + fields[1]
    return None


def test_the_timer_runs_3_minutes_after_boot_and_then_every_30_minutes() -> None:
    timer = read_unit(TIMER_UNIT)

    assert dict(timer["Timer"]) == {
        "OnBootSec": "3min",
        "OnUnitActiveSec": "30min",
        "AccuracySec": "1min",
    }
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_the_service_runs_the_check() -> None:
    service = read_unit(SERVICE)["Service"]

    assert service["Type"] == "oneshot"
    assert service["ExecStart"] == "/usr/sbin/pve-smart-alert check"
    assert installed("libexec/pve-smart-alert") == "/usr/sbin"


def test_a_run_skipped_because_of_the_lock_is_a_success() -> None:
    service = read_unit(SERVICE)["Service"]

    assert service["SuccessExitStatus"] == str(EXIT_LOCKED)


def test_a_failed_run_starts_the_failure_reporter() -> None:
    unit = read_unit(SERVICE)["Unit"]
    failure = read_unit(FAILURE)

    assert unit["OnFailure"] == FAILURE
    command = failure["Service"]["ExecStart"]
    assert command == "/usr/libexec/pve-smart-alert/report-failure"
    assert installed("libexec/report-failure") == str(Path(command).parent)
    # The reporter must not report its own failure in a loop.
    assert "OnFailure" not in failure["Unit"]


def test_the_service_waits_for_pmxcfs_but_does_not_need_it() -> None:
    unit = read_unit(SERVICE)["Unit"]

    assert unit["After"] == "pve-cluster.service"
    for key in ("Requires", "Requisite", "BindsTo", "Wants"):
        assert key not in unit


def test_the_directories_are_the_ones_the_tool_uses() -> None:
    service = read_unit(SERVICE)["Service"]
    failure = read_unit(FAILURE)["Service"]

    assert Path("/run") / service["RuntimeDirectory"] == RUN_DIR
    assert Path("/var/lib") / service["StateDirectory"] == STATE_DIR
    assert service["StateDirectoryMode"] == "0700"
    # The lock and the stamp of the failure reporter stay until a reboot,
    # whichever of the two services ran last.
    assert failure["RuntimeDirectory"] == service["RuntimeDirectory"]
    assert service["RuntimeDirectoryPreserve"] == "yes"
    assert failure["RuntimeDirectoryPreserve"] == "yes"


def test_priority_and_run_time_are_limited() -> None:
    service = read_unit(SERVICE)["Service"]

    assert service["Nice"] == "10"
    assert service["IOSchedulingClass"] == "best-effort"
    assert service["IOSchedulingPriority"] == "7"
    assert service["TimeoutStartSec"] == "15min"


def sandboxing(name: str) -> dict[str, str]:
    """Return the sandboxing options a unit sets."""
    unit = read_unit(name)
    return {
        key: value
        for section in unit.sections()
        for key, value in unit[section].items()
        if SANDBOXING.match(key)
    }


def test_the_service_is_sandboxed_as_adr_0025_decided() -> None:
    # Nothing untested, and nothing that hides the drives from smartctl or
    # makes the mail queue read-only, such as PrivateDevices or
    # ProtectSystem=strict.
    assert sandboxing(SERVICE) == DECIDED_SANDBOXING


@pytest.mark.parametrize("name", [FAILURE, TIMER_UNIT])
def test_the_other_units_are_not_sandboxed(name: str) -> None:
    # The failure reporter is the last resort and stays plain (ADR 0025).
    assert sandboxing(name) == {}


@pytest.mark.parametrize("name", [SERVICE, FAILURE])
def test_the_services_are_never_enabled(name: str) -> None:
    # Only the timer starts a run. A service with an [Install] section would
    # be enabled, and started, by the maintainer scripts.
    assert "Install" not in read_unit(name)


@pytest.mark.parametrize("name", [SERVICE, FAILURE, TIMER_UNIT])
def test_every_unit_is_installed_where_systemd_reads_the_units_of_packages(name: str) -> None:
    assert installed(f"systemd/{name}") == "/usr/lib/systemd/system"


def test_only_the_timer_gets_maintainer_script_snippets() -> None:
    rules = (REPOSITORY / "debian" / "rules").read_text(encoding="utf-8")

    calls = re.findall(r"^\tdh_installsystemd\b.*$", rules, re.MULTILINE)
    assert calls == [f"\tdh_installsystemd {TIMER_UNIT}"]
