# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the transports (ADR 0008).

Neither a bridge nor a mail command is needed: the process runner is a
parameter, so the tests answer for it (ADR 0016).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import Parser
from pathlib import Path

import pytest

from pve_smart_alert.config import NotifySettings, TransportName
from pve_smart_alert.model import MAX_PRINTED, EventType, Notification, Severity
from pve_smart_alert.process import ProcessResult
from pve_smart_alert.transports import (
    AutoTransport,
    MailTransport,
    PveNotifyTransport,
    TransportOutcome,
    build_transport,
)
from pve_smart_alert.transports.base import DEFAULT_TIMEOUT_SECONDS

BRIDGE_LOG = "notified via target 'mail-to-root'\n"


def make_notification(
    *,
    event: EventType = EventType.TEST,
    severity: Severity = Severity.INFO,
    node: str = "pve1",
    subject: str = "PVE SMART Alert: test notification",
    body: str = "This is a test.",
) -> Notification:
    """Return a notification with everything a transport needs."""
    return Notification(
        event=event,
        severity=severity,
        node=node,
        subject=subject,
        body=body,
        fields={"drive": "sda"},
        data={"event": str(event)},
    )


def good_result() -> ProcessResult:
    """What a bridge that handed the message to a target answers."""
    return ProcessResult(returncode=0, stdout='{"ok": true}', stderr=BRIDGE_LOG, timed_out=False)


@dataclass
class FakeRunner:
    """A process runner that answers with a fixed result and records its calls."""

    result: ProcessResult = field(default_factory=good_result)
    failure: OSError | None = None
    calls: list[tuple[list[str], str | None, float]] = field(default_factory=list)

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


class StubTransport:
    """A transport that answers with a fixed outcome and records what it got."""

    def __init__(
        self,
        name: TransportName,
        *,
        delivered: bool = True,
        log_lines: tuple[str, ...] = (),
        error: str | None = None,
        duration_seconds: float = 0.0,
    ) -> None:
        self._name = name
        self._delivered = delivered
        self._log_lines = log_lines
        self._error = error
        self._duration_seconds = duration_seconds
        self.sent: list[Notification] = []

    @property
    def name(self) -> TransportName:
        return self._name

    def send(self, notification: Notification) -> TransportOutcome:
        self.sent.append(notification)
        return TransportOutcome(
            delivered=self._delivered,
            transport=self._name,
            duration_seconds=self._duration_seconds,
            log_lines=self._log_lines,
            error=self._error,
        )


def stdin_of(runner: FakeRunner, index: int = 0) -> str:
    """Return what the run at `index` got on its standard input."""
    text = runner.calls[index][1]
    assert text is not None
    return text


@pytest.fixture
def bridge(tmp_path: Path) -> Path:
    """A file where the bridge is expected."""
    path = tmp_path / "notify-bridge"
    path.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    return path


@pytest.fixture
def sendmail(tmp_path: Path) -> Path:
    """A file where the mail command is expected."""
    path = tmp_path / "sendmail"
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    return path


def parse_mail(text: str) -> EmailMessage:
    """Read back a message that `build_message` wrote."""
    return Parser(policy=policy.default).parsestr(text)


# The bridge transport


def test_a_good_answer_is_a_delivery(bridge: Path) -> None:
    runner = FakeRunner()
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is True
    assert outcome.error is None
    assert outcome.transport is TransportName.PVE_NOTIFY
    assert outcome.log_lines == (BRIDGE_LOG.strip(),)
    assert runner.calls[0][0] == [str(bridge)]
    assert runner.calls[0][2] == DEFAULT_TIMEOUT_SECONDS


def test_the_request_carries_the_notification(bridge: Path) -> None:
    runner = FakeRunner()
    notification = make_notification(severity=Severity.CRITICAL)

    PveNotifyTransport(bridge_path=bridge, runner=runner).send(notification)

    request = json.loads(stdin_of(runner))
    assert request["severity"] == "error"
    assert request["template"] == "pve-smart-alert"
    assert request["fields"] == {
        "drive": "sda",
        "type": "pve-smart-alert",
        "hostname": "pve1",
    }
    assert request["data"]["subject"] == notification.subject
    assert request["data"]["body"] == notification.body
    assert request["data"]["event"] == "test"


def test_a_missing_bridge_is_not_a_delivery(tmp_path: Path) -> None:
    runner = FakeRunner()
    transport = PveNotifyTransport(bridge_path=tmp_path / "absent", runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error is not None
    assert "missing at" in outcome.error
    assert runner.calls == []


def test_a_bridge_that_cannot_be_started_is_not_a_delivery(bridge: Path) -> None:
    runner = FakeRunner(failure=PermissionError(13, "Permission denied"))
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the notify bridge could not be started: Permission denied"


def test_a_refusing_answer_is_not_a_delivery(bridge: Path) -> None:
    runner = FakeRunner(
        result=ProcessResult(0, '{"ok": false, "error": "no target matched"}', "", False)
    )
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the notify bridge reported an error: no target matched"


def test_a_refusing_answer_without_a_reason_is_not_a_delivery(bridge: Path) -> None:
    runner = FakeRunner(result=ProcessResult(0, '{"ok": false}', "", False))
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    assert transport.send(make_notification()).error == (
        "the notify bridge reported an error: no reason given"
    )


def test_a_non_zero_exit_status_is_not_a_delivery(bridge: Path) -> None:
    runner = FakeRunner(result=ProcessResult(2, "", "something went wrong\n", False))
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the notify bridge ended with exit status 2: something went wrong"


def test_a_timeout_is_not_a_delivery(bridge: Path) -> None:
    runner = FakeRunner(result=ProcessResult(None, "", "", True))
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the notify bridge did not answer within 120 seconds"


def test_a_template_that_cannot_be_rendered_is_not_a_delivery(bridge: Path) -> None:
    runner = FakeRunner(
        result=ProcessResult(
            0, '{"ok": true}', "failed to render notification template pve-smart-alert\n", False
        )
    )
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the notification system could not render the template"


def test_targets_that_all_failed_are_not_a_delivery(bridge: Path) -> None:
    runner = FakeRunner(
        result=ProcessResult(0, '{"ok": true}', "could not notify via target 'gotify'\n", False)
    )
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "every matched target of the notification system failed"


def test_one_target_that_worked_is_enough(bridge: Path) -> None:
    log = "could not notify via target 'gotify'\n" + BRIDGE_LOG
    runner = FakeRunner(result=ProcessResult(0, '{"ok": true}', log, False))
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is True
    assert outcome.error is None


def test_an_unknown_log_line_still_counts_as_a_delivery(bridge: Path) -> None:
    # Best effort (ADR 0008): a change of wording in the notification library
    # must not turn every notification into a retry.
    runner = FakeRunner(result=ProcessResult(0, '{"ok": true}', "something new\n", False))
    transport = PveNotifyTransport(bridge_path=bridge, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is True
    assert outcome.error is None


# The mail transport


def test_mail_is_handed_to_the_mail_command(sendmail: Path) -> None:
    runner = FakeRunner()
    notification = make_notification()

    outcome = MailTransport(sendmail_path=sendmail, runner=runner).send(notification)

    assert outcome.delivered is True
    assert outcome.transport is TransportName.MAIL
    assert runner.calls[0][0] == [str(sendmail), "-i", "-t"]
    message = parse_mail(stdin_of(runner))
    assert message["To"] == "root"
    assert message["Subject"] == notification.subject
    assert message.get_content().rstrip("\n") == notification.body


def test_mail_with_characters_outside_ascii_is_encoded(sendmail: Path) -> None:
    runner = FakeRunner()
    notification = make_notification(
        subject="PVE SMART Alert: Laufwerk schlägt fehl", body="Zustand: schlecht"
    )

    MailTransport(sendmail_path=sendmail, runner=runner).send(notification)

    text = stdin_of(runner)
    assert "=?utf-8?" in text
    message = parse_mail(text)
    assert str(message["Subject"]) == notification.subject
    assert message.get_content().rstrip("\n") == notification.body


def test_a_missing_mail_command_is_not_a_delivery(tmp_path: Path) -> None:
    runner = FakeRunner()
    transport = MailTransport(sendmail_path=tmp_path / "absent", runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error is not None
    assert "missing at" in outcome.error
    assert runner.calls == []


def test_a_mail_command_that_cannot_be_started_is_not_a_delivery(sendmail: Path) -> None:
    runner = FakeRunner(failure=PermissionError(13, "Permission denied"))
    transport = MailTransport(sendmail_path=sendmail, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the mail command could not be started: Permission denied"


def test_a_refusing_mail_command_is_not_a_delivery(sendmail: Path) -> None:
    runner = FakeRunner(result=ProcessResult(1, "", "unknown user\n", False))
    transport = MailTransport(sendmail_path=sendmail, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the mail command ended with exit status 1: unknown user"


def test_a_mail_timeout_is_not_a_delivery(sendmail: Path) -> None:
    runner = FakeRunner(result=ProcessResult(None, "", "", True))
    transport = MailTransport(sendmail_path=sendmail, runner=runner)

    outcome = transport.send(make_notification())

    assert outcome.delivered is False
    assert outcome.error == "the mail command did not answer within 120 seconds"


# Automatic fallback


def test_the_primary_transport_is_used_when_it_works() -> None:
    primary = StubTransport(TransportName.PVE_NOTIFY, log_lines=("notified via target x",))
    fallback = StubTransport(TransportName.MAIL)

    outcome = AutoTransport(primary=primary, fallback=fallback).send(make_notification())

    assert outcome.delivered is True
    assert outcome.transport is TransportName.PVE_NOTIFY
    assert outcome.fallback_reason is None
    assert outcome.error is None
    assert fallback.sent == []


def test_the_fallback_takes_over_and_names_the_reason() -> None:
    primary = StubTransport(
        TransportName.PVE_NOTIFY,
        delivered=False,
        error="every matched target of the notification system failed",
        log_lines=("could not notify via target x",),
        duration_seconds=0.5,
    )
    fallback = StubTransport(TransportName.MAIL, log_lines=("sent",), duration_seconds=0.25)

    outcome = AutoTransport(primary=primary, fallback=fallback).send(make_notification())

    assert outcome.delivered is True
    assert outcome.transport is TransportName.MAIL
    assert outcome.fallback_reason == "every matched target of the notification system failed"
    assert outcome.error is None
    assert outcome.log_lines == ("could not notify via target x", "sent")
    assert outcome.duration_seconds == 0.75
    note = fallback.sent[0]
    assert "was sent as mail" in note.body
    assert "pve-notify" in note.body
    assert note.body.endswith("Reason: every matched target of the notification system failed\n")


def test_the_reason_of_the_fallback_carries_no_control_character() -> None:
    # The reason is the answer of the bridge or of the mail command, an
    # external program; it can carry an escape sequence or a line of its own
    # (ARCHITECTURE.md section 14). The mail that is delivered is where it
    # used to arrive unchanged.
    primary = StubTransport(
        TransportName.PVE_NOTIFY,
        delivered=False,
        error="refused: \x1b[2J550\nInjected: fake line",
    )
    fallback = StubTransport(TransportName.MAIL)

    AutoTransport(primary=primary, fallback=fallback).send(make_notification())

    body = fallback.sent[0].body
    assert "\x1b" not in body
    assert "\nInjected" not in body
    assert body.endswith("Reason: refused: [2J550 Injected: fake line\n")


def test_a_cut_reason_of_the_fallback_carries_the_mark() -> None:
    # A cut value carries the mark, as in every other message (ADR 0036).
    primary = StubTransport(
        TransportName.PVE_NOTIFY, delivered=False, error="refused: " + "x" * 300
    )
    fallback = StubTransport(TransportName.MAIL)

    AutoTransport(primary=primary, fallback=fallback).send(make_notification())

    body = fallback.sent[0].body
    # Cut exactly at the limit: one more character would mean another limit.
    assert body.endswith("Reason: refused: " + "x" * (MAX_PRINTED - len("refused: ")) + "…\n")
    assert "x" * (MAX_PRINTED - len("refused: ") + 1) + "…" not in body


def test_a_failure_without_a_reason_is_still_reported() -> None:
    primary = StubTransport(TransportName.PVE_NOTIFY, delivered=False)
    fallback = StubTransport(TransportName.MAIL)

    outcome = AutoTransport(primary=primary, fallback=fallback).send(make_notification())

    assert outcome.delivered is True
    assert outcome.fallback_reason == "the primary transport failed"


def test_the_failure_of_both_transports_is_reported() -> None:
    primary = StubTransport(
        TransportName.PVE_NOTIFY, delivered=False, error="the bridge is missing"
    )
    fallback = StubTransport(
        TransportName.MAIL, delivered=False, error="the mail command is missing"
    )

    outcome = AutoTransport(primary=primary, fallback=fallback).send(make_notification())

    assert outcome.delivered is False
    assert outcome.transport is TransportName.MAIL
    assert outcome.error == (
        "the bridge is missing; the fallback failed as well: the mail command is missing"
    )


# Building the configured transport


def test_auto_builds_both_transports(tmp_path: Path) -> None:
    transport = build_transport(
        NotifySettings(),
        bridge_path=tmp_path / "bridge",
        sendmail_path=tmp_path / "sendmail",
    )

    assert isinstance(transport, AutoTransport)
    assert transport.name is TransportName.AUTO
    assert isinstance(transport.primary, PveNotifyTransport)
    assert transport.primary.bridge_path == tmp_path / "bridge"
    assert isinstance(transport.fallback, MailTransport)
    assert transport.fallback.sendmail_path == tmp_path / "sendmail"


def test_mail_builds_the_mail_transport(tmp_path: Path) -> None:
    transport = build_transport(
        NotifySettings(transport=TransportName.MAIL),
        bridge_path=tmp_path / "bridge",
        sendmail_path=tmp_path / "sendmail",
    )

    assert isinstance(transport, MailTransport)
    assert transport.sendmail_path == tmp_path / "sendmail"


def test_the_bridge_builds_the_bridge_transport(tmp_path: Path) -> None:
    transport = build_transport(
        NotifySettings(transport=TransportName.PVE_NOTIFY),
        bridge_path=tmp_path / "bridge",
        sendmail_path=tmp_path / "sendmail",
    )

    assert isinstance(transport, PveNotifyTransport)
    assert transport.bridge_path == tmp_path / "bridge"
