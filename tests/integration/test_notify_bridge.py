# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract test of the notify bridge against a stub of `PVE::Notify` (ADR 0016).

The bridge is the one piece of the tool whose counterpart is Perl, so the test
runs the real script with the real interpreter and a stub in `@INC`. It needs
neither root nor a Proxmox VE host. Without Perl and JSON::PP it skips itself.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
BRIDGE = REPOSITORY / "libexec" / "notify-bridge"
STUBS = REPOSITORY / "tests" / "perl-stubs"

PERL = shutil.which("perl")


def perl_can_load(module: str) -> bool:
    """Return whether the interpreter can load a module."""
    if PERL is None:
        return False
    return subprocess.run([PERL, "-M" + module, "-e", "1"], capture_output=True).returncode == 0


requires_perl = pytest.mark.skipif(
    PERL is None or not os.access(BRIDGE, os.X_OK) or not perl_can_load("JSON::PP"),
    reason="an executable bridge and perl with JSON::PP are needed",
)


@dataclass(frozen=True)
class BridgeRun:
    """What one run of the bridge left behind."""

    returncode: int
    stdout: str
    stderr: str
    log: Path

    @property
    def answer(self) -> dict[str, Any]:
        """The document the bridge wrote to its standard output."""
        return cast("dict[str, Any]", json.loads(self.stdout))

    @property
    def calls(self) -> list[dict[str, Any]]:
        """The calls the stub recorded, one per line of its log."""
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [cast("dict[str, Any]", json.loads(line)) for line in lines]


def request_document(**changes: Any) -> str:
    """Return a valid bridge request, with single fields replaced."""
    document: dict[str, Any] = {
        "severity": "warning",
        "template": "pve-smart-alert",
        "fields": {"type": "pve-smart-alert", "hostname": "pve1"},
        "data": {"subject": "Subject", "body": "Body"},
    }
    document.update(changes)
    return json.dumps(document)


def run_bridge(
    tmp_path: Path,
    *,
    request: str = "",
    mode: str = "ok",
    arguments: Sequence[str] = (),
) -> BridgeRun:
    """Run the bridge with the stub module in `@INC`."""
    log = tmp_path / f"stub-{mode}.jsonl"
    libraries = [str(STUBS)]
    if os.environ.get("PERL5LIB"):
        libraries.append(os.environ["PERL5LIB"])

    environment = dict(os.environ)
    environment["PERL5LIB"] = os.pathsep.join(libraries)
    environment["PVE_SMART_ALERT_STUB_MODE"] = mode
    environment["PVE_SMART_ALERT_STUB_LOG"] = str(log)

    result = subprocess.run(
        [str(BRIDGE), *arguments],
        input=request,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return BridgeRun(result.returncode, result.stdout, result.stderr, log)


# The self-check


@requires_perl
def test_the_check_accepts_a_usable_bridge(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, mode="ok", arguments=["--check"])

    assert run.returncode == 0
    assert run.answer == {"ok": True}
    assert run.calls == []


@requires_perl
def test_the_check_reports_a_module_without_notify(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, mode="no-notify", arguments=["--check"])

    assert run.returncode == 1
    assert run.answer["ok"] is False
    assert "does not offer notify()" in run.answer["error"]


@requires_perl
def test_an_unknown_argument_is_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, mode="ok", arguments=["--send"])

    assert run.returncode != 0
    assert "usage: notify-bridge" in run.stderr


# The call


@requires_perl
def test_a_notification_reaches_the_module(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document())

    assert run.returncode == 0
    assert run.answer == {"ok": True}
    assert len(run.calls) == 1
    call = run.calls[0]
    assert call["severity"] == "warning"
    assert call["template"] == "pve-smart-alert"
    assert call["fields"] == {"type": "pve-smart-alert", "hostname": "pve1"}
    assert call["data"]["subject"] == "Subject"
    assert call["data"]["body"] == "Body"


@requires_perl
def test_the_common_template_data_is_added(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document())

    data = run.calls[0]["data"]
    assert data["hostname"] == "pve1"
    assert data["fqdn"] == "pve1.example.test"
    assert data["cluster-name"] == "test"


@requires_perl
def test_the_data_of_the_request_wins(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(data={"hostname": "pve2"}))

    assert run.calls[0]["data"]["hostname"] == "pve2"


@requires_perl
def test_a_module_without_common_template_data_still_works(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(), mode="no-common")

    assert run.returncode == 0
    assert set(run.calls[0]["data"]) == {"subject", "body"}


@requires_perl
def test_text_outside_ascii_survives(tmp_path: Path) -> None:
    request = request_document(
        data={"subject": "Laufwerk schlägt fehl", "body": "Zustand: schlecht"}
    )

    run = run_bridge(tmp_path, request=request)

    assert run.calls[0]["data"]["subject"] == "Laufwerk schlägt fehl"


# What the notification system logged


@requires_perl
def test_the_log_of_the_library_reaches_standard_error(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(), mode="ok")

    # The Python side classifies exactly these lines (ADR 0008).
    assert "notified via target 'mail-to-root'" in run.stderr


@requires_perl
def test_a_failed_target_is_visible(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(), mode="all-targets-failed")

    # The bridge handed the message over; whether a target got it is the
    # judgement of the caller.
    assert run.returncode == 0
    assert "could not notify via target 'mail-to-root'" in run.stderr


@requires_perl
def test_a_rendering_failure_is_visible(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(), mode="render-failed")

    assert "failed to render notification template" in run.stderr


@requires_perl
def test_a_dying_call_is_an_error(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(), mode="die")

    assert run.returncode == 1
    assert run.answer["ok"] is False
    assert "the stub was told to die" in run.answer["error"]
    assert len(run.calls) == 1


# Requests that are not usable


@requires_perl
def test_a_request_that_is_not_json_is_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request="this is not JSON")

    assert run.returncode == 1
    assert "not valid JSON" in run.answer["error"]
    assert run.calls == []


@requires_perl
def test_a_request_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request="[]")

    assert run.answer["error"] == "the request must be an object"
    assert run.calls == []


@requires_perl
def test_a_missing_severity_is_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(severity=None))

    assert run.answer["error"] == "the severity is missing or unknown: none"
    assert run.calls == []


@requires_perl
def test_an_unknown_severity_is_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(severity="fatal"))

    assert "the severity is missing or unknown: fatal" in run.answer["error"]
    assert run.calls == []


@requires_perl
def test_a_missing_template_name_is_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(template=""))

    assert run.answer["error"] == "the template name is missing"
    assert run.calls == []


@requires_perl
def test_data_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(data=[]))

    assert run.answer["error"] == "data must be an object"
    assert run.calls == []


@requires_perl
def test_fields_that_are_not_an_object_are_refused(tmp_path: Path) -> None:
    run = run_bridge(tmp_path, request=request_document(fields=[]))

    assert run.answer["error"] == "fields must be an object"
    assert run.calls == []
