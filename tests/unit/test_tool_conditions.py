# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the detection of the conditions of the tool itself (FR-518).

The programs the detection runs, smartctl and the notify bridge, are
replaced by a runner that answers as the test says (ADR 0016).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pve_smart_alert.config import (
    TOOL_CHECK_IDS,
    ConfigError,
    NotifySettings,
    SmartctlSettings,
    TransportName,
)
from pve_smart_alert.model import CheckKind, Severity
from pve_smart_alert.process import ProcessResult
from pve_smart_alert.tool_conditions import (
    TOOL_CONDITIONS,
    config_invalid,
    scan_failed,
    smartctl_missing,
    smartctl_too_old,
    transport_degraded,
)


class Answers:
    """A runner that answers every program with the same result, and keeps the calls."""

    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,  # noqa: ARG002
        timeout: float,  # noqa: ARG002
    ) -> ProcessResult:
        self.calls.append([str(part) for part in command])
        return self.result


def answering(stdout: str = "", returncode: int = 0) -> Answers:
    return Answers(ProcessResult(returncode=returncode, stdout=stdout, stderr="", timed_out=False))


def executable(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_the_conditions_have_the_severities_of_the_catalog() -> None:
    # docs/check-catalog.md, "Conditions of the tool itself".
    assert {name: condition.severity for name, condition in TOOL_CONDITIONS.items()} == {
        "tool.smartctl_missing": Severity.CRITICAL,
        "tool.smartctl_too_old": Severity.CRITICAL,
        "tool.scan_failed": Severity.WARNING,
        "tool.config_invalid": Severity.WARNING,
        "tool.state_reset": Severity.NOTICE,
        "tool.transport_degraded": Severity.WARNING,
        "tool.unsupported_controller": Severity.NOTICE,
    }
    assert TOOL_CONDITIONS["tool.state_reset"].kind is CheckKind.EVENT


def test_the_configuration_knows_every_condition_of_the_tool() -> None:
    # config.py cannot import this module without a cycle, so it repeats the
    # identifiers as the ones it accepts in [checks] (ADR 0031).
    assert frozenset(TOOL_CONDITIONS) == TOOL_CHECK_IDS


def test_a_missing_smartctl(tmp_path: Path) -> None:
    missing = smartctl_missing(SmartctlSettings(path=tmp_path / "smartctl"))

    assert missing is not None
    assert missing.check == "tool.smartctl_missing"
    assert str(tmp_path / "smartctl") in missing.text


def test_a_smartctl_that_cannot_be_executed(tmp_path: Path) -> None:
    path = tmp_path / "smartctl"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)

    missing = smartctl_missing(SmartctlSettings(path=path))

    assert missing is not None
    assert "not executable" in missing.text
    assert smartctl_missing(SmartctlSettings(path=executable(tmp_path, "other"))) is None


def test_the_version_of_the_scan_decides(tmp_path: Path) -> None:
    runner = answering()
    settings = SmartctlSettings(path=executable(tmp_path, "smartctl"))

    assert smartctl_too_old(settings, (7, 5), runner=runner) is None
    old = smartctl_too_old(settings, (6, 6), runner=runner)

    assert old is not None
    assert "version 6.6" in old.text
    assert runner.calls == []


def test_without_a_version_the_text_version_is_asked_for(tmp_path: Path) -> None:
    # A smartctl older than 7.0 writes no JSON, so its device scan fails.
    settings = SmartctlSettings(path=executable(tmp_path, "smartctl"))
    runner = answering("smartctl 6.6 2016-05-31 r4324 [x86_64-linux-4.9.0] (local build)\n")

    old = smartctl_too_old(settings, (), runner=runner)

    assert old is not None
    assert old.check == "tool.smartctl_too_old"
    assert runner.calls == [[str(settings.path), "--version"]]
    assert smartctl_too_old(settings, (), runner=answering("no version here")) is None


def test_a_failed_scan() -> None:
    assert scan_failed(None) is None
    failed = scan_failed("the device scan answered without valid JSON")
    assert failed is not None
    assert failed.severity is Severity.WARNING


def test_an_invalid_configuration_names_what_runs_use() -> None:
    invalid = config_invalid(
        ConfigError('unknown key "x"', line=3), fallback="the built-in defaults"
    )

    assert invalid.check == "tool.config_invalid"
    assert 'unknown key "x" (line 3)' in invalid.text
    assert "the built-in defaults" in invalid.text


def test_a_bridge_that_loads_is_no_condition(tmp_path: Path) -> None:
    bridge = executable(tmp_path, "notify-bridge")
    runner = answering('{"ok": true}')

    assert transport_degraded(NotifySettings(), bridge, runner=runner) is None
    assert runner.calls == [[str(bridge), "--check"]]


def test_a_bridge_that_fails_degrades_the_transport(tmp_path: Path) -> None:
    bridge = executable(tmp_path, "notify-bridge")
    runner = answering('{"ok": false, "error": "PVE::Notify cannot be loaded"}', returncode=1)

    degraded = transport_degraded(NotifySettings(), bridge, runner=runner)

    assert degraded is not None
    assert degraded.check == "tool.transport_degraded"
    assert "PVE::Notify cannot be loaded" in degraded.text
    assert "as mail to root" in degraded.text


def test_a_missing_bridge_with_the_primary_transport_only(tmp_path: Path) -> None:
    settings = NotifySettings(transport=TransportName.PVE_NOTIFY)

    degraded = transport_degraded(settings, tmp_path / "notify-bridge", runner=answering())

    assert degraded is not None
    assert "cannot be delivered" in degraded.text


def test_the_mail_transport_has_no_bridge_to_fail(tmp_path: Path) -> None:
    runner = answering()
    settings = NotifySettings(transport=TransportName.MAIL)

    assert transport_degraded(settings, tmp_path / "notify-bridge", runner=runner) is None
    assert runner.calls == []
