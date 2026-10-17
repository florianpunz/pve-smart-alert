# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the self-diagnosis (FR-603).

Every path is a parameter, so the checks run against a temporary directory
instead of the host (ADR 0016).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hosts import CLUSTER_NODE_SCSI_HOSTS, write_scsi_hosts, write_sg_nodes

from pve_smart_alert import cli
from pve_smart_alert.config import (
    DiscoverySettings,
    NotifySettings,
    SmartctlSettings,
    TransportName,
    load_config,
    save_last_good,
)
from pve_smart_alert.discovery import HostPaths
from pve_smart_alert.doctor import (
    FALLBACK_ADVICE,
    TEMPLATES,
    CheckResult,
    Status,
    check_bridge,
    check_config,
    check_fallback,
    check_mail,
    check_probe,
    check_pve,
    check_routing,
    check_smartctl,
    check_smartd,
    check_state,
    check_templates,
    check_timer,
    read_routes,
    run_doctor,
)
from pve_smart_alert.process import ProcessResult
from pve_smart_alert.routing import NotificationConfig, RoutingError
from pve_smart_alert.state import LastRun, State, save_state
from pve_smart_alert.transports.base import DEFAULT_TIMEOUT_SECONDS


class StaticRunner:
    """A process runner that answers with a fixed result and records its calls."""

    def __init__(self, result: ProcessResult, failure: OSError | None = None) -> None:
        self.result = result
        self.failure = failure
        self.calls: list[tuple[list[str], str | None, float]] = []

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> ProcessResult:
        self.calls.append(([str(argument) for argument in command], input_text, timeout))
        if self.failure is not None:
            raise self.failure
        return self.result


def good_bridge() -> ProcessResult:
    """What a bridge that loaded the notification system answers."""
    return ProcessResult(returncode=0, stdout='{"ok": true}', stderr="", timed_out=False)


@pytest.fixture
def bridge(tmp_path: Path) -> Path:
    """A file where the bridge is expected, executable like the installed one."""
    path = tmp_path / "notify-bridge"
    path.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def vendor_dir(tmp_path: Path) -> Path:
    """A directory with both template files in it."""
    path = tmp_path / "templates"
    path.mkdir()
    for name in TEMPLATES:
        (path / name.name).write_text("{{subject}}\n", encoding="utf-8")
    return path


# The configuration


def test_a_missing_configuration_is_fine(tmp_path: Path) -> None:
    result, config = check_config(tmp_path / "config.toml")

    assert result.status is Status.OK
    assert "the defaults apply" in result.detail
    assert config is not None
    assert config.notify.transport is TransportName.AUTO


def test_the_configuration_is_reported_with_its_transport(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[notify]\ntransport = "mail"\n', encoding="utf-8")

    result, config = check_config(path)

    assert result.status is Status.OK
    assert result.detail == f"{path}: transport = mail"
    assert config is not None
    assert config.notify.transport is TransportName.MAIL


def test_an_unusable_configuration_warns_and_a_run_continues(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[notify]\ntimeout = 30\n", encoding="utf-8")

    result, config = check_config(path, last_good=None)

    # The run continues with the built-in defaults, so this is a warning and
    # not a failure (FR-406).
    assert result.status is Status.WARN
    assert "unknown key" in result.detail
    assert "built-in defaults" in result.detail
    assert config is not None
    assert config.notify.transport is TransportName.AUTO


def test_an_unusable_configuration_names_the_last_good_one(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[notify]\ntimeout = 30\n", encoding="utf-8")
    good = tmp_path / "good.toml"
    good.write_text('[notify]\ntransport = "mail"\n', encoding="utf-8")
    last_good = tmp_path / "last-good-config.json"
    save_last_good(load_config(good), last_good)

    result, config = check_config(path, last_good=last_good)

    assert result.status is Status.WARN
    assert "last good configuration" in result.detail
    assert config is not None
    assert config.notify.transport is TransportName.MAIL


# The bridge


def test_the_bridge_is_asked_to_check_itself(bridge: Path) -> None:
    runner = StaticRunner(good_bridge())

    result = check_bridge(bridge, runner=runner)

    assert result.status is Status.OK
    # The self-check reads no notification and must not hang either.
    assert runner.calls == [([str(bridge), "--check"], None, DEFAULT_TIMEOUT_SECONDS)]


def test_a_missing_bridge_fails(tmp_path: Path) -> None:
    result = check_bridge(tmp_path / "absent", runner=StaticRunner(good_bridge()))

    assert result.status is Status.FAIL
    assert "missing at" in result.detail
    assert result.advice is not None


def test_a_bridge_that_is_not_executable_fails(tmp_path: Path) -> None:
    path = tmp_path / "notify-bridge"
    path.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    path.chmod(0o644)

    result = check_bridge(path, runner=StaticRunner(good_bridge()))

    assert result.status is Status.FAIL
    assert "not executable" in result.detail


def test_a_bridge_that_cannot_be_started_fails(bridge: Path) -> None:
    runner = StaticRunner(good_bridge(), failure=PermissionError(13, "Permission denied"))

    result = check_bridge(bridge, runner=runner)

    assert result.status is Status.FAIL
    assert "could not be started: Permission denied" in result.detail


def test_a_bridge_that_reports_an_error_fails(bridge: Path) -> None:
    answer = '{"ok": false, "error": "PVE::Notify does not offer notify()"}'
    runner = StaticRunner(ProcessResult(0, answer, "", False))

    result = check_bridge(bridge, runner=runner)

    assert result.status is Status.FAIL
    assert "does not offer notify()" in result.detail


def test_a_bridge_that_ends_with_an_error_fails(bridge: Path) -> None:
    runner = StaticRunner(ProcessResult(2, "", "Can't locate JSON/PP.pm in @INC\n", False))

    result = check_bridge(bridge, runner=runner)

    assert result.status is Status.FAIL
    assert "exit status 2" in result.detail
    assert "Can't locate JSON/PP.pm" in result.detail


def test_a_bridge_that_does_not_answer_fails(bridge: Path) -> None:
    runner = StaticRunner(ProcessResult(None, "", "", True))

    result = check_bridge(bridge, runner=runner)

    assert result.status is Status.FAIL
    assert "did not answer within 120 seconds" in result.detail


# The templates


def test_both_templates_in_the_vendor_directory_are_fine(tmp_path: Path, vendor_dir: Path) -> None:
    result = check_templates(vendor_dir, override_dir=tmp_path / "override")

    assert result.status is Status.OK
    assert result.detail == str(vendor_dir)


def test_the_override_directory_wins(tmp_path: Path, vendor_dir: Path) -> None:
    override = tmp_path / "override"
    override.mkdir()
    for name in TEMPLATES:
        (override / name.name).write_text("{{subject}}\n", encoding="utf-8")

    result = check_templates(vendor_dir, override_dir=override)

    assert result.status is Status.OK
    assert result.detail == str(override)


def test_a_missing_template_fails(tmp_path: Path, vendor_dir: Path) -> None:
    (vendor_dir / TEMPLATES[0].name).unlink()
    override = tmp_path / "override"

    result = check_templates(vendor_dir, override_dir=override)

    assert result.status is Status.FAIL
    assert result.detail == f"missing: {TEMPLATES[0].name}"
    # The advice names both places the notification system looks in (ADR 0008).
    assert result.advice is not None
    assert str(vendor_dir) in result.advice
    assert str(override) in result.advice


def test_templates_from_two_directories_are_reported(tmp_path: Path, vendor_dir: Path) -> None:
    override = tmp_path / "override"
    override.mkdir()
    (override / TEMPLATES[0].name).write_text("{{subject}}\n", encoding="utf-8")

    result = check_templates(vendor_dir, override_dir=override)

    assert result.status is Status.OK
    assert result.detail == f"{override}, {vendor_dir}"


# The mail command


def test_a_mail_command_that_is_there_is_fine(tmp_path: Path) -> None:
    path = tmp_path / "sendmail"
    path.write_text("#!/bin/sh\n", encoding="utf-8")

    result = check_mail(path, settings=NotifySettings(TransportName.AUTO))

    assert result.status is Status.OK
    assert result.detail == str(path)


@pytest.mark.parametrize("transport", [TransportName.AUTO, TransportName.MAIL])
def test_a_missing_mail_command_fails_when_it_is_the_route(
    tmp_path: Path, transport: TransportName
) -> None:
    result = check_mail(tmp_path / "absent", settings=NotifySettings(transport))

    assert result.status is Status.FAIL
    assert "missing at" in result.detail


def test_a_missing_mail_command_only_warns_for_the_bridge(tmp_path: Path) -> None:
    settings = NotifySettings(TransportName.PVE_NOTIFY)

    result = check_mail(tmp_path / "absent", settings=settings)

    assert result.status is Status.WARN


def test_without_a_configuration_the_default_route_counts(tmp_path: Path) -> None:
    # `auto` is the default, and it falls back to mail.
    result = check_mail(tmp_path / "absent", settings=None)

    assert result.status is Status.FAIL


# The routing


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pvesh"
NODE = "pve7"
TOOL_MATCHER = {
    "match-field": ["regex:type=^pve-smart-alert$"],
    "match-severity": ["info,notice,warning,error"],
    "mode": "all",
    "name": "pve-smart-alert",
    "target": ["smtp-relay"],
}


def recorded(name: str) -> NotificationConfig:
    """Return one configuration of `tests/fixtures/pvesh`."""
    directory = FIXTURES / name
    return NotificationConfig.from_json(
        (directory / "matchers.json").read_text(encoding="utf-8"),
        (directory / "targets.json").read_text(encoding="utf-8"),
    )


def constructed(
    *matchers: Mapping[str, object], disabled_targets: Sequence[str] = ()
) -> NotificationConfig:
    """Return these matchers with the target `smtp-relay`, enabled unless named."""
    target: dict[str, object] = {"name": "smtp-relay", "origin": "user-created", "type": "smtp"}
    if "smtp-relay" in disabled_targets:
        target["disable"] = 1
    return NotificationConfig(matchers=tuple(matchers), targets=(target,))


class PveshRunner:
    """Answers the two calls of pvesh from one configuration of the fixtures."""

    def __init__(self, name: str) -> None:
        self.directory = FIXTURES / name
        self.calls: list[tuple[list[str], str | None, float]] = []

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> ProcessResult:
        self.calls.append(([str(argument) for argument in command], input_text, timeout))
        part = str(command[2]).rsplit("/", 1)[-1]
        stdout = (self.directory / f"{part}.json").read_text(encoding="utf-8")
        return ProcessResult(returncode=0, stdout=stdout, stderr="", timed_out=False)


@pytest.fixture
def pvesh(tmp_path: Path) -> Path:
    """A file where pvesh is expected."""
    path = tmp_path / "pvesh"
    path.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def forward(tmp_path: Path) -> Path:
    """A `/root/.forward` as the package proxmox-mail-forward writes it."""
    path = tmp_path / "forward"
    path.write_text("|/usr/libexec/proxmox-mail-forward\n", encoding="utf-8")
    return path


def routing_of(
    routes: NotificationConfig | RoutingError,
    forward: Path,
    *,
    transport: TransportName = TransportName.AUTO,
    node: str = NODE,
) -> CheckResult:
    return check_routing(
        routes, settings=NotifySettings(transport), node=node, forward_path=forward
    )


def fallback_of(
    routes: NotificationConfig | RoutingError,
    forward: Path,
    *,
    transport: TransportName = TransportName.AUTO,
) -> CheckResult:
    return check_fallback(
        routes, settings=NotifySettings(transport), node=NODE, forward_path=forward
    )


def test_the_matchers_are_read_once_through_pvesh(pvesh: Path) -> None:
    runner = PveshRunner("test-cluster-c")

    assert read_routes(pvesh, runner=runner) == recorded("test-cluster-c")
    assert [call[0][2] for call in runner.calls] == [
        "/cluster/notifications/matchers",
        "/cluster/notifications/targets",
    ]


def test_matchers_that_cannot_be_read_are_returned_as_the_reason(tmp_path: Path) -> None:
    runner = PveshRunner("test-cluster-c")

    routes = read_routes(tmp_path / "pvesh", runner=runner)

    assert isinstance(routes, RoutingError)
    assert str(routes) == f"pvesh is missing at {tmp_path / 'pvesh'}"
    assert runner.calls == []


def test_every_severity_with_a_route_is_fine(forward: Path) -> None:
    result = routing_of(recorded("test-cluster-c"), forward)

    assert result == CheckResult(
        "routing", Status.OK, "every severity is routed, by pve-smart-alert"
    )


def test_the_unchanged_default_matcher_routes_everything(forward: Path) -> None:
    result = routing_of(recorded("builtin-default"), forward)

    assert result == CheckResult(
        "routing", Status.OK, "every severity is routed, by default-matcher"
    )


def test_a_severity_without_a_route_is_a_warning(forward: Path) -> None:
    # The matcher left by M1 routes only warning and error (Research 06).
    result = routing_of(recorded("test-cluster-a"), forward)

    assert result.status is Status.WARN
    assert result.detail == "not routed: info, notice"
    # Nothing matches info and notice, so the advice says how to add a
    # matcher (ADR 0020).
    assert result.advice == (
        "add info, notice to a matcher with the rule regex:type=^pve-smart-alert$,"
        " under Datacenter > Notifications, see the README"
    )


def test_a_disabled_matcher_that_would_route_is_named(forward: Path) -> None:
    # Configuration B: the matcher of the tool is disabled (Research 06).
    result = routing_of(recorded("test-cluster-b"), forward)

    assert result.status is Status.WARN
    assert result.detail == "not routed: info, notice, warning, error"
    assert result.advice == (
        "matcher pve-smart-alert matches warning, error, but it is disabled;"
        " add info, notice to a matcher with the rule regex:type=^pve-smart-alert$,"
        " under Datacenter > Notifications, see the README"
    )


def test_enabling_the_matcher_is_the_whole_advice(forward: Path) -> None:
    result = routing_of(constructed({**TOOL_MATCHER, "disable": 1}), forward)

    assert result.advice == (
        "matcher pve-smart-alert matches info, notice, warning, error, but it is disabled"
    )


def test_a_matcher_whose_target_is_disabled_is_named(forward: Path) -> None:
    result = routing_of(constructed(TOOL_MATCHER, disabled_targets=["smtp-relay"]), forward)

    assert result.status is Status.WARN
    assert result.advice == (
        "matcher pve-smart-alert matches info, notice, warning, error,"
        " but its target smtp-relay is disabled"
    )


def test_a_routing_that_cannot_be_decided_is_not_reported_as_routed(forward: Path) -> None:
    routes = constructed(
        {
            "match-calendar": ["mon..fri 8-17"],
            "mode": "all",
            "name": "office-hours",
            "target": ["smtp-relay"],
        }
    )

    result = routing_of(routes, forward)

    # Never `ok`, and not a failure either (ADR 0020).
    assert result.status is Status.SKIP
    assert result.detail == "cannot be decided for: info, notice, warning, error"
    assert result.advice == (
        "matcher office-hours: the time rule mon..fri 8-17 makes the routing depend on the time"
    )


def test_a_severity_without_a_route_outweighs_an_undecided_one(forward: Path) -> None:
    routes = constructed(
        {
            "match-calendar": ["mon..fri 8-17"],
            "match-severity": ["warning,error"],
            "mode": "all",
            "name": "office-hours",
            "target": ["smtp-relay"],
        }
    )

    result = routing_of(routes, forward)

    assert result.status is Status.WARN
    assert result.detail == "not routed: info, notice; cannot be decided for: warning, error"


def test_the_routing_is_checked_for_this_node(forward: Path) -> None:
    routes = constructed(
        {
            "match-field": ["exact:hostname=pve7"],
            "mode": "all",
            "name": "pve7-only",
            "target": ["smtp-relay"],
        }
    )

    assert routing_of(routes, forward, node="pve7").status is Status.OK
    assert routing_of(routes, forward, node="pve5").status is Status.WARN


def test_matchers_that_cannot_be_read_skip_the_routing(forward: Path) -> None:
    # Not an error of the host, only a check that cannot be done (ADR 0020).
    result = routing_of(RoutingError("pvesh is missing at /usr/bin/pvesh"), forward)

    assert result == CheckResult(
        "routing", Status.SKIP, "the matchers cannot be read: pvesh is missing at /usr/bin/pvesh"
    )


def test_the_mail_transport_is_checked_as_mail_to_root(forward: Path) -> None:
    # With transport = mail every notification goes as mail (ADR 0022).
    routed = routing_of(recorded("test-cluster-a"), forward, transport=TransportName.MAIL)
    dropped = routing_of(recorded("test-cluster-b"), forward, transport=TransportName.MAIL)

    assert routed == CheckResult(
        "routing",
        Status.OK,
        "transport = mail: mail to root is routed as system-mail, by default-matcher",
    )
    assert dropped.status is Status.WARN
    assert dropped.detail.startswith("transport = mail: mail to root is not routed")


# The fallback


@pytest.mark.parametrize("name", ["test-cluster-a", "test-cluster-c", "builtin-default"])
def test_mail_to_root_with_a_route_is_fine(forward: Path, name: str) -> None:
    result = fallback_of(recorded(name), forward)

    assert result == CheckResult(
        "fallback", Status.OK, "mail to root is routed as system-mail, by default-matcher"
    )


def test_mail_to_root_without_a_route_is_a_warning(forward: Path) -> None:
    # In configuration B the default matcher routes only vzdump, so the
    # fallback of the tool would be dropped as well (Research 06).
    result = fallback_of(recorded("test-cluster-b"), forward)

    assert result.status is Status.WARN
    assert result.detail == (
        "mail to root is not routed: no matcher routes the type system-mail to an enabled target"
    )
    assert result.advice == FALLBACK_ADVICE
    assert "exact:type=system-mail" in FALLBACK_ADVICE
    assert "severity unknown" in FALLBACK_ADVICE


def test_a_disabled_default_matcher_is_named(forward: Path) -> None:
    routes = constructed(
        {"disable": 1, "mode": "all", "name": "default-matcher", "target": ["smtp-relay"]}
    )

    result = fallback_of(routes, forward)

    assert result.status is Status.WARN
    assert result.advice == "matcher default-matcher matches, but it is disabled"


def test_mail_that_does_not_reach_the_notification_system_is_a_warning(tmp_path: Path) -> None:
    missing = tmp_path / "forward"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("admin@example.com\n", encoding="utf-8")

    for path in (missing, elsewhere):
        result = fallback_of(recorded("builtin-default"), path)

        assert result.status is Status.WARN
        assert result.detail == (
            "mail to root does not reach the notification system:"
            f" {path} has no line for proxmox-mail-forward"
        )
        assert (
            result.advice == "reinstalling the package proxmox-mail-forward writes the line into it"
        )


def test_a_forward_file_that_cannot_be_read_is_skipped(tmp_path: Path) -> None:
    # A directory stands for a file this process may not read.
    result = fallback_of(recorded("builtin-default"), tmp_path)

    assert result.status is Status.SKIP
    assert result.detail.endswith(f"{tmp_path} cannot be read")


def test_a_quoted_line_of_the_forward_file_counts(tmp_path: Path) -> None:
    path = tmp_path / "forward"
    path.write_text('# mail for root\n"|/usr/libexec/proxmox-mail-forward"\n', encoding="utf-8")

    assert fallback_of(recorded("builtin-default"), path).status is Status.OK


def test_a_fallback_that_cannot_be_decided_is_skipped(forward: Path) -> None:
    routes = constructed(
        {
            "match-calendar": ["mon..fri 8-17"],
            "mode": "all",
            "name": "office-hours",
            "target": ["smtp-relay"],
        }
    )

    result = fallback_of(routes, forward)

    assert result.status is Status.SKIP
    assert result.detail == "cannot be decided for mail to root"
    assert result.advice is not None
    assert "time rule" in result.advice


def test_matchers_that_cannot_be_read_skip_the_fallback(forward: Path) -> None:
    result = fallback_of(RoutingError("pvesh is missing at /usr/bin/pvesh"), forward)

    assert result.status is Status.SKIP
    assert result.detail == "the matchers cannot be read: pvesh is missing at /usr/bin/pvesh"


@pytest.mark.parametrize(
    ("transport", "detail"),
    [
        (TransportName.PVE_NOTIFY, "transport = pve-notify has no fallback"),
        (TransportName.MAIL, "transport = mail has no fallback, mail to root is its route"),
    ],
)
def test_only_the_automatic_transport_has_a_fallback(
    forward: Path, transport: TransportName, detail: str
) -> None:
    result = fallback_of(recorded("test-cluster-b"), forward, transport=transport)

    assert result == CheckResult("fallback", Status.SKIP, detail)


# smartctl


FAKE = Path(__file__).resolve().parent.parent / "fake-smartctl"
RECORDINGS = Path(__file__).resolve().parent.parent / "fixtures" / "smartctl" / "direct"


def scan_answer(version: list[int]) -> ProcessResult:
    stdout = json.dumps(
        {"json_format_version": [1, 0], "smartctl": {"version": version}, "devices": []}
    )
    return ProcessResult(returncode=0, stdout=stdout, stderr="", timed_out=False)


def test_smartctl_is_reported_with_its_version(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real program code against the fake smartctl and a recording of 7.5.
    monkeypatch.setenv("FAKE_SMARTCTL_RECORDING", str(RECORDINGS / "test-cluster-pve7"))

    result = check_smartctl(SmartctlSettings(path=FAKE))

    assert result == CheckResult("smartctl", Status.OK, f"{FAKE}: smartctl 7.5")


def test_the_version_comes_from_a_scan_that_opens_nothing(bridge: Path) -> None:
    runner = StaticRunner(scan_answer([7, 4]))

    result = check_smartctl(SmartctlSettings(path=bridge), runner=runner)

    assert result.detail.endswith("smartctl 7.4")
    assert runner.calls[0][0] == [str(bridge), "--scan", "--json=c"]


def test_a_missing_smartctl_fails(tmp_path: Path) -> None:
    result = check_smartctl(SmartctlSettings(path=tmp_path / "smartctl"))

    assert result.status is Status.FAIL
    assert result.advice == "it comes with the package smartmontools"


def test_a_smartctl_older_than_7_fails(bridge: Path) -> None:
    result = check_smartctl(SmartctlSettings(path=bridge), runner=StaticRunner(scan_answer([6, 6])))

    assert result.status is Status.FAIL
    assert "found 6.6" in result.detail


def test_a_smartctl_without_json_fails(bridge: Path) -> None:
    # smartctl before 7.0 does not understand --json.
    answer = ProcessResult(returncode=1, stdout="smartctl 6.6 ...\n", stderr="", timed_out=False)

    result = check_smartctl(SmartctlSettings(path=bridge), runner=StaticRunner(answer))

    assert result.status is Status.FAIL
    assert result.advice == "the tool needs smartmontools 7.0 or later (ADR 0002)"


def test_a_smartctl_that_does_not_answer_fails(bridge: Path) -> None:
    runner = StaticRunner(ProcessResult(None, "", "", True))

    result = check_smartctl(SmartctlSettings(path=bridge, timeout_seconds=30.0), runner=runner)

    assert result.detail.endswith("did not answer within 30 seconds")


# The timer

# What `systemctl show` writes for the installed timer, with both entries of
# the unit and a monotonic next start, which is a time since boot.
TIMER_SHOWN = """\
LoadState=loaded
ActiveState=active
UnitFileState=enabled
TimersMonotonic={ OnBootUSec=3min ; next_elapse=3min }
TimersMonotonic={ OnUnitActiveUSec=30min ; next_elapse=1d 2h 30min 1.5s }
"""

# What `systemctl list-timers --output=json` writes for it, as recorded with
# systemd 255: the next start in microseconds since the epoch.
TIMER_LISTED = (
    '[{"next":1792091837866509,"left":1792091837866509,"last":1792005437857614,'
    '"passed":87306838507,"unit":"pve-smart-alert.timer",'
    '"activates":"pve-smart-alert.service"}]'
)


def answer(stdout: str, *, returncode: int = 0, stderr: str = "") -> ProcessResult:
    """Return what a program that wrote `stdout` left behind."""
    return ProcessResult(returncode=returncode, stdout=stdout, stderr=stderr, timed_out=False)


def executable(path: Path) -> Path:
    """Create an executable file at `path` and return it."""
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class SystemctlRunner:
    """Answers `systemctl show` and `systemctl list-timers` and records the calls."""

    def __init__(self, shown: ProcessResult, listed: ProcessResult | None = None) -> None:
        self.shown = shown
        self.listed = answer(TIMER_LISTED) if listed is None else listed
        self.calls: list[tuple[list[str], str | None, float]] = []

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> ProcessResult:
        arguments = [str(argument) for argument in command]
        self.calls.append((arguments, input_text, timeout))
        return self.shown if "show" in arguments else self.listed


def shown_with(**changes: str) -> ProcessResult:
    """Return the shown timer with some properties replaced."""
    lines = []
    for line in TIMER_SHOWN.splitlines():
        key = line.partition("=")[0]
        lines.append(f"{key}={changes[key]}" if key in changes else line)
    return answer("\n".join(lines) + "\n")


def test_an_active_and_enabled_timer_is_reported_with_its_schedule(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")

    result = check_timer(systemctl, runner=SystemctlRunner(answer(TIMER_SHOWN)))

    assert result.status is Status.OK
    assert result.detail == (
        "pve-smart-alert.timer is active, every 30min after the start of the last run,"
        " next run 2026-10-15T19:17:17Z"
    )


def test_the_timer_is_only_asked(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")
    runner = SystemctlRunner(answer(TIMER_SHOWN))

    check_timer(systemctl, runner=runner)

    # Nothing but reading: no start, enable or reload (ADR 0012).
    commands = [arguments for arguments, _, _ in runner.calls]
    assert [arguments[1] for arguments in commands] == ["show", "list-timers"]
    assert all(arguments[0] == str(systemctl) for arguments in commands)
    assert all("pve-smart-alert.timer" in arguments for arguments in commands)
    assert all(input_text is None for _, input_text, _ in runner.calls)


def test_a_schedule_changed_by_a_drop_in_is_the_one_reported(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")
    shown = answer(
        "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
        "TimersCalendar={ OnCalendar=*-*-* *:00:00 ; next_elapse=Thu 2026-10-15 10:00:00 UTC }\n"
    )

    result = check_timer(systemctl, runner=SystemctlRunner(shown))

    assert result.status is Status.OK
    assert "on *-*-* *:00:00" in result.detail
    assert "every" not in result.detail


def test_a_timer_that_is_not_active_fails(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")

    result = check_timer(systemctl, runner=SystemctlRunner(shown_with(ActiveState="inactive")))

    assert result.status is Status.FAIL
    assert result.detail == "pve-smart-alert.timer is inactive, no check runs by itself"
    assert result.advice == "systemctl enable --now pve-smart-alert.timer"


def test_a_timer_that_is_not_enabled_warns_about_the_next_reboot(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")

    result = check_timer(systemctl, runner=SystemctlRunner(shown_with(UnitFileState="disabled")))

    assert result.status is Status.WARN
    assert "but it is disabled, so the runs stop with the next reboot" in result.detail
    assert result.advice == "systemctl enable pve-smart-alert.timer"


def test_a_timer_that_is_not_installed_fails(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")
    shown = answer("LoadState=not-found\nActiveState=inactive\nUnitFileState=\n")

    result = check_timer(systemctl, runner=SystemctlRunner(shown))

    assert result.status is Status.FAIL
    assert result.detail == "pve-smart-alert.timer is not installed"


def test_without_systemctl_the_timer_is_skipped(tmp_path: Path) -> None:
    result = check_timer(tmp_path / "systemctl", runner=SystemctlRunner(answer(TIMER_SHOWN)))

    assert result.status is Status.SKIP
    assert "missing" in result.detail


def test_a_systemd_that_does_not_run_skips_the_timer(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")
    refused = answer(
        "", returncode=1, stderr="System has not been booted with systemd as init system (PID 1).\n"
    )

    result = check_timer(systemctl, runner=SystemctlRunner(refused))

    assert result.status is Status.SKIP
    assert result.detail.startswith("systemd cannot be asked: System has not been booted")


def test_systemctl_that_cannot_be_started_skips_the_timer(tmp_path: Path) -> None:
    systemctl = executable(tmp_path / "systemctl")

    refuse = StaticRunner(answer(""), failure=PermissionError(13, "Permission denied"))

    result = check_timer(systemctl, runner=refuse)

    assert result.status is Status.SKIP
    assert result.detail.endswith("could not be started: Permission denied")


@pytest.mark.parametrize(
    "listed",
    [
        answer("", returncode=1, stderr="Unknown option --output\n"),
        answer("not json"),
        answer('[{"unit":"pve-smart-alert.timer","next":0}]'),
        answer('[{"unit":"other.timer","next":1792091837866509}]'),
        answer('{"unit":"pve-smart-alert.timer"}'),
    ],
)
def test_a_next_run_that_systemd_does_not_tell_is_left_out(
    tmp_path: Path, listed: ProcessResult
) -> None:
    systemctl = executable(tmp_path / "systemctl")

    result = check_timer(systemctl, runner=SystemctlRunner(answer(TIMER_SHOWN), listed))

    assert result.status is Status.OK
    assert result.detail == (
        "pve-smart-alert.timer is active, every 30min after the start of the last run"
    )


# The whole run


class HostRunner:
    """Answers the bridge, and smartctl with a scan of 7.5, and records the calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None, float]] = []

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> ProcessResult:
        arguments = [str(argument) for argument in command]
        self.calls.append((arguments, input_text, timeout))
        if "--scan" in arguments:
            return scan_answer([7, 5])
        if "show" in arguments:
            return answer(TIMER_SHOWN)
        if "list-timers" in arguments:
            return answer(TIMER_LISTED)
        return good_bridge()


def doctor_on(tmp_path: Path, bridge: Path, vendor_dir: Path, sendmail: Path) -> list[CheckResult]:
    smartctl = tmp_path / "smartctl"
    smartctl.write_text("#!/bin/sh\n", encoding="utf-8")
    smartctl.chmod(0o755)
    config = tmp_path / "config.toml"
    config.write_text(f'[smartctl]\npath = "{smartctl}"\n', encoding="utf-8")
    return run_doctor(
        config_path=config,
        bridge_path=bridge,
        sendmail_path=sendmail,
        template_dir=vendor_dir,
        override_dir=tmp_path / "override",
        pvesh_path=tmp_path / "pvesh",
        forward_path=tmp_path / "forward",
        state_path=tmp_path / "state.json",
        systemctl_path=executable(tmp_path / "systemctl"),
        pveversion_path=tmp_path / "pveversion",
        smartd_conf_path=tmp_path / "smartd.conf",
        host_paths=HostPaths(sysfs=tmp_path / "sys"),
        node="pve1",
        runner=HostRunner(),
    )


def test_a_working_host_reports_no_failure(tmp_path: Path, bridge: Path, vendor_dir: Path) -> None:
    sendmail = tmp_path / "sendmail"
    sendmail.write_text("#!/bin/sh\n", encoding="utf-8")

    results = doctor_on(tmp_path, bridge, vendor_dir, sendmail)

    assert [result.name for result in results] == [
        "config",
        "smartctl",
        "bridge",
        "templates",
        "mail",
        "routing",
        "fallback",
        "state",
        "timer",
        "pve",
        "smartd",
        "controllers",
        "probe",
    ]
    assert all(result.status is not Status.FAIL for result in results)
    assert results[1].detail.endswith("smartctl 7.5")


def test_the_controllers_are_read_from_the_sysfs_it_is_given(
    tmp_path: Path, bridge: Path, vendor_dir: Path
) -> None:
    # Every part of FR-603 is checked; the line `controllers` is one of them.
    write_scsi_hosts(tmp_path / "sys", CLUSTER_NODE_SCSI_HOSTS)

    results = doctor_on(tmp_path, bridge, vendor_dir, tmp_path / "sendmail")
    controllers = next(result for result in results if result.name == "controllers")

    assert controllers.status is Status.OK
    assert controllers.detail == "6 SCSI hosts (ahci), none whose drives smartctl cannot read"


# The line `probe` (FR-103, ADR 0032)


def probe_on(
    tmp_path: Path,
    drivers: dict[int, str],
    *,
    nodes: dict[int, int] | None = None,
    probe_cciss: bool = True,
) -> CheckResult:
    sysfs = tmp_path / "sys"
    write_scsi_hosts(sysfs, drivers)
    write_sg_nodes(sysfs, {} if nodes is None else nodes)
    return check_probe(DiscoverySettings(probe_cciss=probe_cciss), HostPaths(sysfs=sysfs))


def test_a_host_without_an_hpe_controller_has_nothing_to_probe(tmp_path: Path) -> None:
    result = probe_on(tmp_path, CLUSTER_NODE_SCSI_HOSTS)

    assert result.status is Status.OK
    assert result.detail == "no HPE Smart Array controller"


def test_an_hpsa_controller_is_named_with_its_node(tmp_path: Path) -> None:
    result = probe_on(tmp_path, {0: "ahci", 1: "hpsa"}, nodes={1: 1})

    assert result.status is Status.OK
    assert "SCSI host 1 has the driver hpsa and is probed as cciss,N on /dev/sg1" in result.detail
    assert result.advice is None


def test_a_smartpqi_controller_is_named_and_warns(tmp_path: Path) -> None:
    # smartctl supports -d cciss,N only for hpsa (ADR 0032): the drives of such
    # a controller are found only as manual entries.
    result = probe_on(tmp_path, {1: "smartpqi"}, nodes={1: 1})

    assert result.status is Status.WARN
    assert "smartctl supports -d cciss,N only for the driver hpsa" in result.detail
    assert result.advice is not None
    assert "[[discovery.device]]" in result.advice


def test_an_hpsa_controller_without_a_node_warns(tmp_path: Path) -> None:
    result = probe_on(tmp_path, {1: "hpsa"})

    assert result.status is Status.WARN
    assert "no SCSI generic node (/dev/sgN) of this host was found" in result.detail
    assert result.advice is not None
    assert "sg driver" in result.advice


def test_a_switched_off_probe_is_no_warning(tmp_path: Path) -> None:
    result = probe_on(tmp_path, {1: "hpsa"}, nodes={1: 1}, probe_cciss=False)

    assert result.status is Status.OK
    assert "the probe is switched off with probe_cciss = false" in result.detail


def test_without_sysfs_the_probe_line_is_skipped(tmp_path: Path) -> None:
    directory = tmp_path / "sys" / "class" / "scsi_host"
    directory.parent.mkdir(parents=True)
    directory.write_text("", encoding="utf-8")

    result = check_probe(DiscoverySettings(), HostPaths(sysfs=tmp_path / "sys"))

    assert result.status is Status.SKIP


# The command


def results_with(status: Status) -> list[CheckResult]:
    """Return one result per line of the report, with the given status."""
    return [
        CheckResult("config", Status.OK, "no file at /etc/pve-smart-alert/config.toml"),
        CheckResult("bridge", status, "missing at /usr/libexec/pve-smart-alert/notify-bridge"),
    ]


def test_the_report_is_printed_with_aligned_labels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run_doctor", lambda: results_with(Status.OK))

    assert cli.main(["doctor"]) == cli.EXIT_OK

    assert capsys.readouterr().out == (
        "config:      ok    no file at /etc/pve-smart-alert/config.toml\n"
        "bridge:      ok    missing at /usr/libexec/pve-smart-alert/notify-bridge\n"
    )


def test_a_failed_check_ends_with_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run_doctor", lambda: results_with(Status.FAIL))

    assert cli.main(["doctor"]) == cli.EXIT_PROBLEM

    assert "bridge:      fail  missing at" in capsys.readouterr().out


def test_an_advice_is_printed_below_its_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = [CheckResult("bridge", Status.FAIL, "missing", advice="it comes with the package")]
    monkeypatch.setattr(cli, "run_doctor", lambda: results)

    cli.main(["doctor"])

    assert capsys.readouterr().out == (
        "bridge:      fail  missing\n                   it comes with the package\n"
    )


def test_a_warning_does_not_end_with_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run_doctor", lambda: results_with(Status.WARN))

    assert cli.main(["doctor"]) == cli.EXIT_OK

    assert "bridge:      warn" in capsys.readouterr().out


# The state file (FR-603)


def test_without_a_state_file_the_next_run_is_a_first_run(tmp_path: Path) -> None:
    result = check_state(tmp_path / "state.json")

    assert result.status is Status.OK
    assert "first run" in result.detail


def test_the_state_file_names_the_last_run(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    started = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
    save_state(State(last_run=LastRun(started=started, finished=started, result="ok")), path)

    result = check_state(path)

    assert result.status is Status.OK
    assert "last run 2026-10-12T08:00:00Z, ok, 0 active conditions" in result.detail


def test_a_last_run_that_could_not_deliver_warns(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    started = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
    run = LastRun(started, started, "notifications not delivered", notifications_failed=1)
    save_state(State(last_run=run), path)

    assert check_state(path).status is Status.WARN


def test_a_corrupt_state_file_warns_and_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")

    result = check_state(path)

    assert result.status is Status.WARN
    assert result.advice is not None
    assert "sets the file aside" in result.advice
    assert path.read_text(encoding="utf-8") == "{broken"


# Proxmox VE and smartd (FR-603, ADR 0002, ADR 0012)


class SystemRunner:
    """Answers systemctl and pveversion as a host would, from what the test sets."""

    def __init__(self, units: Mapping[str, str], timers: str = "[]", pve: str = "") -> None:
        self.units = units
        self.timers = timers
        self.pve = pve

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,  # noqa: ARG002
        timeout: float,  # noqa: ARG002
    ) -> ProcessResult:
        arguments = [str(argument) for argument in command]
        if "show" in arguments:
            stdout = self.units.get(arguments[-1], "LoadState=not-found\nActiveState=inactive\n")
        elif "list-timers" in arguments:
            stdout = self.timers
        else:
            stdout = self.pve
        return ProcessResult(returncode=0, stdout=stdout, stderr="", timed_out=False)


@pytest.fixture
def systemctl(tmp_path: Path) -> Path:
    path = tmp_path / "systemctl"
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("output", "status", "detail"),
    [
        ("pve-manager/9.2.3/d0fde103346cf89a (running kernel: 7.0.6-2-pve)\n", Status.OK, "9.2.3"),
        ("pve-manager/10.0.1/abc (running kernel: 7.2)\n", Status.WARN, "10.0.1"),
        ("something else\n", Status.SKIP, "no version"),
    ],
)
def test_the_version_of_proxmox_ve(
    tmp_path: Path, output: str, status: Status, detail: str
) -> None:
    pveversion = tmp_path / "pveversion"
    pveversion.write_text("#!/bin/sh\n", encoding="utf-8")

    result = check_pve(pveversion, runner=SystemRunner({}, pve=output))

    assert result.status is status
    assert detail in result.detail


def test_without_pveversion_the_version_is_skipped(tmp_path: Path) -> None:
    assert check_pve(tmp_path / "pveversion", runner=SystemRunner({})).status is Status.SKIP


SMARTD_ACTIVE = {"smartmontools.service": "LoadState=loaded\nActiveState=active\n"}


def test_smartd_with_the_debian_default_mails_root(systemctl: Path, tmp_path: Path) -> None:
    # Research 02: the default line of Proxmox VE mails root every day.
    config = tmp_path / "smartd.conf"
    config.write_text(
        "# comment\nDEVICESCAN -d removable -n standby -m root -M exec"
        " /usr/share/smartmontools/smartd-runner\n",
        encoding="utf-8",
    )

    result = check_smartd(systemctl, config, runner=SystemRunner(SMARTD_ACTIVE))

    assert result.status is Status.OK
    assert "mails root (DEVICESCAN -d removable -n standby -m root" in result.detail
    assert result.advice is not None


def test_smartd_that_only_logs(systemctl: Path, tmp_path: Path) -> None:
    config = tmp_path / "smartd.conf"
    config.write_text("DEVICESCAN -d removable -n standby\n#-m root\n", encoding="utf-8")

    result = check_smartd(systemctl, config, runner=SystemRunner(SMARTD_ACTIVE))

    assert result.detail.endswith("sends no mail")
    assert result.advice is None


def test_smartd_with_the_no_mailer_address_sends_no_mail(systemctl: Path, tmp_path: Path) -> None:
    config = tmp_path / "smartd.conf"
    config.write_text("DEVICESCAN -m <nomailer> -M exec /usr/local/bin/log\n", encoding="utf-8")

    result = check_smartd(systemctl, config, runner=SystemRunner(SMARTD_ACTIVE))

    assert result.detail.endswith("sends no mail")


def test_smartd_that_is_not_active(systemctl: Path, tmp_path: Path) -> None:
    result = check_smartd(systemctl, tmp_path / "smartd.conf", runner=SystemRunner({}))

    assert result.status is Status.OK
    assert result.detail.startswith("not active")
