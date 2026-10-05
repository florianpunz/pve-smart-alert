# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the self-diagnosis (FR-603).

Every path is a parameter, so the checks run against a temporary directory
instead of the host (ADR 0016).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from pve_smart_alert import cli
from pve_smart_alert.config import NotifySettings, TransportName
from pve_smart_alert.doctor import (
    TEMPLATES,
    CheckResult,
    Status,
    check_bridge,
    check_config,
    check_mail,
    check_routing,
    check_templates,
    run_doctor,
)
from pve_smart_alert.process import ProcessResult
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
    result, settings = check_config(tmp_path / "config.toml")

    assert result.status is Status.OK
    assert "the defaults apply" in result.detail
    assert settings is not None
    assert settings.transport is TransportName.AUTO


def test_the_configuration_is_reported_with_its_transport(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[notify]\ntransport = "mail"\n', encoding="utf-8")

    result, settings = check_config(path)

    assert result.status is Status.OK
    assert result.detail == f"{path}: transport = mail"
    assert settings is not None
    assert settings.transport is TransportName.MAIL


def test_an_unusable_configuration_fails(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[notify]\ntimeout = 30\n", encoding="utf-8")

    result, settings = check_config(path)

    assert result.status is Status.FAIL
    assert "unknown key" in result.detail
    assert settings is None


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


class PveshRunner:
    """Answers the two calls of pvesh with the matchers and targets given."""

    def __init__(self, answers: Mapping[str, str]) -> None:
        self.answers = answers
        self.calls: list[tuple[list[str], str | None, float]] = []

    @classmethod
    def recorded(cls, name: str) -> PveshRunner:
        """Answer with one configuration of `tests/fixtures/pvesh`."""
        directory = FIXTURES / name
        return cls(
            {
                part: (directory / f"{part}.json").read_text(encoding="utf-8")
                for part in ("matchers", "targets")
            }
        )

    @classmethod
    def constructed(cls, *matchers: dict[str, object]) -> PveshRunner:
        """Answer with these matchers and one enabled target `relay`."""
        targets = [{"name": "relay", "origin": "user-created", "type": "smtp"}]
        return cls({"matchers": json.dumps(matchers), "targets": json.dumps(targets)})

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> ProcessResult:
        self.calls.append(([str(argument) for argument in command], input_text, timeout))
        part = str(command[2]).rsplit("/", 1)[-1]
        return ProcessResult(returncode=0, stdout=self.answers[part], stderr="", timed_out=False)


@pytest.fixture
def pvesh(tmp_path: Path) -> Path:
    """A file where pvesh is expected."""
    path = tmp_path / "pvesh"
    path.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def routing_of(
    pvesh: Path, runner: PveshRunner | StaticRunner, *, node: str = "pve7"
) -> CheckResult:
    """Return the routing line for the default transport."""
    return check_routing(pvesh, settings=None, node=node, runner=runner)


def test_every_severity_with_a_route_is_fine(pvesh: Path) -> None:
    result = routing_of(pvesh, PveshRunner.recorded("test-cluster-c"))

    assert result == CheckResult(
        "routing", Status.OK, "every severity is routed, by pve-smart-alert"
    )


def test_the_unchanged_default_matcher_routes_everything(pvesh: Path) -> None:
    result = routing_of(pvesh, PveshRunner.recorded("builtin-default"))

    assert result == CheckResult(
        "routing", Status.OK, "every severity is routed, by default-matcher"
    )


def test_a_severity_without_a_route_is_a_warning(pvesh: Path) -> None:
    # The matcher left by M1 routes only warning and error (Research 06).
    result = routing_of(pvesh, PveshRunner.recorded("test-cluster-a"))

    assert result.status is Status.WARN
    assert result.detail == "not routed: info, notice"
    # The advice says how to add a matcher (ADR 0020).
    assert result.advice is not None
    assert "regex:type=^pve-smart-alert$" in result.advice


def test_a_disabled_matcher_of_the_tool_leaves_no_route(pvesh: Path) -> None:
    result = routing_of(pvesh, PveshRunner.recorded("test-cluster-b"))

    assert result.status is Status.WARN
    assert result.detail == "not routed: info, notice, warning, error"


def test_a_routing_that_cannot_be_decided_is_not_reported_as_routed(pvesh: Path) -> None:
    runner = PveshRunner.constructed(
        {
            "match-calendar": ["mon..fri 8-17"],
            "mode": "all",
            "name": "office-hours",
            "target": ["relay"],
        }
    )

    result = routing_of(pvesh, runner)

    # Never `ok`, and not a failure either (ADR 0020).
    assert result.status is Status.SKIP
    assert result.detail == "cannot be decided for: info, notice, warning, error"
    assert result.advice == (
        "matcher office-hours: the time rule mon..fri 8-17 makes the routing depend on the time"
    )


def test_a_severity_without_a_route_outweighs_an_undecided_one(pvesh: Path) -> None:
    runner = PveshRunner.constructed(
        {
            "match-calendar": ["mon..fri 8-17"],
            "match-severity": ["warning,error"],
            "mode": "all",
            "name": "office-hours",
            "target": ["relay"],
        }
    )

    result = routing_of(pvesh, runner)

    assert result.status is Status.WARN
    assert result.detail == "not routed: info, notice; cannot be decided for: warning, error"


def test_the_routing_is_checked_for_this_node(pvesh: Path) -> None:
    runner = PveshRunner.constructed(
        {
            "match-field": ["exact:hostname=pve7"],
            "mode": "all",
            "name": "pve7-only",
            "target": ["relay"],
        }
    )

    assert routing_of(pvesh, runner, node="pve7").status is Status.OK
    assert routing_of(pvesh, runner, node="pve5").status is Status.WARN


def test_without_pvesh_the_routing_is_skipped(tmp_path: Path) -> None:
    runner = StaticRunner(good_bridge())

    result = routing_of(tmp_path / "pvesh", runner)

    assert result == CheckResult(
        "routing",
        Status.SKIP,
        f"the matchers cannot be read: pvesh is missing at {tmp_path / 'pvesh'}",
    )
    assert runner.calls == []


def test_an_api_that_cannot_be_asked_is_skipped(pvesh: Path) -> None:
    # Not an error of the host, only a check that cannot be done (ADR 0020).
    runner = StaticRunner(ProcessResult(255, "", "an error of pvesh\n", False))

    result = routing_of(pvesh, runner)

    assert result.status is Status.SKIP
    assert result.detail.endswith("ended with exit status 255: an error of pvesh")


def test_the_mail_transport_is_not_followed(pvesh: Path) -> None:
    runner = PveshRunner.recorded("test-cluster-b")

    result = check_routing(
        pvesh, settings=NotifySettings(TransportName.MAIL), node="pve7", runner=runner
    )

    assert result.status is Status.SKIP
    assert "system-mail" in result.detail
    assert runner.calls == []


# The whole run


def test_a_working_host_reports_no_failure(tmp_path: Path, bridge: Path, vendor_dir: Path) -> None:
    sendmail = tmp_path / "sendmail"
    sendmail.write_text("#!/bin/sh\n", encoding="utf-8")

    results = run_doctor(
        config_path=tmp_path / "config.toml",
        bridge_path=bridge,
        sendmail_path=sendmail,
        template_dir=vendor_dir,
        override_dir=tmp_path / "override",
        pvesh_path=tmp_path / "pvesh",
        node="pve1",
        runner=StaticRunner(good_bridge()),
    )

    assert [result.name for result in results] == [
        "config",
        "bridge",
        "templates",
        "mail",
        "routing",
        "pending",
    ]
    assert all(result.status is not Status.FAIL for result in results)


def test_what_is_not_checked_yet_is_named(tmp_path: Path, bridge: Path, vendor_dir: Path) -> None:
    results = run_doctor(
        config_path=tmp_path / "config.toml",
        bridge_path=bridge,
        sendmail_path=tmp_path / "sendmail",
        template_dir=vendor_dir,
        override_dir=tmp_path / "override",
        pvesh_path=tmp_path / "pvesh",
        node="pve1",
        runner=StaticRunner(good_bridge()),
    )

    pending = results[-1]
    assert pending.status is Status.SKIP
    assert "smartctl" in pending.detail


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
