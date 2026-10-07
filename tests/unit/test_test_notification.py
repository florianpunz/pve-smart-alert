# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the `test-notification` command and the rendering behind it."""

from __future__ import annotations

from pathlib import Path

import pytest

from pve_smart_alert import cli
from pve_smart_alert.config import Config, ConfigError, NotifySettings, TransportName
from pve_smart_alert.model import EventType, Notification, PveSeverity, Severity
from pve_smart_alert.render import render_test_notification
from pve_smart_alert.routing import NotificationConfig, RoutingError
from pve_smart_alert.transports import TransportOutcome

NODE = "pve1"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pvesh"


class FakeTransport:
    """A transport that answers with a fixed outcome and records what it got."""

    def __init__(
        self,
        *,
        delivered: bool = True,
        transport: TransportName = TransportName.PVE_NOTIFY,
        log_lines: tuple[str, ...] = (),
        fallback_reason: str | None = None,
        error: str | None = None,
        duration_seconds: float = 0.0,
    ) -> None:
        self._outcome = TransportOutcome(
            delivered=delivered,
            transport=transport,
            duration_seconds=duration_seconds,
            log_lines=log_lines,
            fallback_reason=fallback_reason,
            error=error,
        )
        self.sent: list[Notification] = []

    @property
    def name(self) -> TransportName:
        return self._outcome.transport

    def send(self, notification: Notification) -> TransportOutcome:
        self.sent.append(notification)
        return self._outcome


def install(
    monkeypatch: pytest.MonkeyPatch,
    transport: FakeTransport,
    *,
    config: Config | None = None,
    config_error: ConfigError | None = None,
    matchers: NotificationConfig | None = None,
    forwarded: bool | None = True,
) -> list[NotifySettings]:
    """Let the command see this transport and this configuration.

    `matchers` is what the routing check reads; without it, the matchers
    cannot be read, as on a host without `pvesh`. `forwarded` is whether
    mail to root reaches the notification system. Returns the settings the
    command built its transport from.
    """
    seen: list[NotifySettings] = []

    def build(settings: NotifySettings) -> FakeTransport:
        seen.append(settings)
        return transport

    def load() -> Config:
        if config_error is not None:
            raise config_error
        return config if config is not None else Config()

    def read_matchers() -> NotificationConfig:
        if matchers is None:
            raise RoutingError("pvesh is missing at /usr/bin/pvesh")
        return matchers

    monkeypatch.setattr(cli, "node_name", lambda: NODE)
    monkeypatch.setattr(cli, "build_transport", build)
    monkeypatch.setattr(cli, "load_config", load)
    monkeypatch.setattr(cli, "read_notification_config", read_matchers)
    monkeypatch.setattr(cli, "mail_is_forwarded", lambda: forwarded)
    return seen


def recorded(name: str) -> NotificationConfig:
    """Return one configuration of `tests/fixtures/pvesh`."""
    directory = FIXTURES / name
    return NotificationConfig.from_json(
        (directory / "matchers.json").read_text(encoding="utf-8"),
        (directory / "targets.json").read_text(encoding="utf-8"),
    )


# Rendering


def test_the_test_notification_is_rendered() -> None:
    notification = render_test_notification(Severity.INFO, node=NODE)

    assert notification.event is EventType.TEST
    assert notification.severity is Severity.INFO
    assert notification.node == NODE
    assert notification.subject == "[pve-smart-alert] INFO pve1: test notification"
    assert NODE in notification.body
    assert notification.fields_for() == {
        "event": "test",
        "type": "pve-smart-alert",
        "hostname": "pve1",
    }


@pytest.mark.parametrize("severity", list(Severity))
def test_the_subject_names_the_severity(severity: Severity) -> None:
    # The mail route carries no severity, so the subject has to (ADR 0008).
    notification = render_test_notification(severity, node=NODE)

    assert notification.subject.startswith(f"[pve-smart-alert] {severity.value.upper()} pve1: ")


# The command


def test_a_delivered_notification_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport(
        log_lines=("notified via target 'mail-to-root'",), duration_seconds=0.42
    )
    install(monkeypatch, transport)

    assert cli.main(["test-notification"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "Transport: auto" in out
    assert "Severity:  info" in out
    assert "Delivered: yes" in out
    assert "Used:      pve-notify" in out
    assert "Duration:  0.42 s" in out
    assert "Log:\n  notified via target 'mail-to-root'\n" in out


def test_the_default_severity_is_info(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    install(monkeypatch, transport)

    cli.main(["test-notification"])

    assert transport.sent[0].severity is Severity.INFO


def test_the_severity_can_be_chosen(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    install(monkeypatch, transport)

    assert cli.main(["test-notification", "--severity", "warning"]) == cli.EXIT_OK

    assert transport.sent[0].severity is Severity.WARNING
    assert "Severity:  warning" in capsys.readouterr().out


def test_the_severity_error_becomes_critical(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    install(monkeypatch, transport)

    assert cli.main(["test-notification", "--severity", "error"]) == cli.EXIT_OK

    # The tool names this severity `critical`, Proxmox VE names it `error`.
    assert transport.sent[0].severity is Severity.CRITICAL
    assert "Severity:  error" in capsys.readouterr().out


def test_a_not_delivered_notification_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport(
        delivered=False,
        transport=TransportName.MAIL,
        error="every matched target of the notification system failed",
    )
    install(monkeypatch, transport)

    assert cli.main(["test-notification"]) == cli.EXIT_PROBLEM

    out = capsys.readouterr().out
    assert "Delivered: no" in out
    assert "Error:     every matched target of the notification system failed" in out
    assert "Used:" not in out


def test_the_fallback_reason_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport(
        transport=TransportName.MAIL,
        fallback_reason=(
            "the notify bridge is missing at /usr/libexec/pve-smart-alert/notify-bridge"
        ),
    )
    install(monkeypatch, transport)

    assert cli.main(["test-notification"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "Used:      mail" in out
    assert "Fallback:  the notify bridge is missing at" in out


def test_an_empty_log_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeTransport())

    cli.main(["test-notification"])

    # Nothing logged can also mean that no matcher matched (ADR 0008).
    out = capsys.readouterr().out
    assert "  (the notification system logged nothing)" in out
    assert "no matcher matched" in out


def test_the_log_lines_are_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport(log_lines=("first line", "second line"))
    install(monkeypatch, transport)

    cli.main(["test-notification"])

    assert "  first line\n  second line\n" in capsys.readouterr().out


def test_the_configured_transport_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config(notify=NotifySettings(TransportName.MAIL))
    seen = install(monkeypatch, FakeTransport(), config=config)

    assert cli.main(["test-notification"]) == cli.EXIT_OK

    assert seen[0].transport is TransportName.MAIL


def test_the_transport_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = install(monkeypatch, FakeTransport())

    assert cli.main(["test-notification", "--transport", "mail"]) == cli.EXIT_OK

    assert seen[0].transport is TransportName.MAIL
    assert "Transport: mail" in capsys.readouterr().out


def test_a_configuration_error_exits_with_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    error = ConfigError('unknown key "timeout" in section [notify]', key="notify.timeout", line=3)
    install(monkeypatch, FakeTransport(), config_error=error)

    assert cli.main(["test-notification"]) == cli.EXIT_USAGE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pve-smart-alert: unknown key" in captured.err


def test_a_configuration_error_is_reported_even_with_a_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The next run will not have the override, so the broken file stays an error.
    install(monkeypatch, FakeTransport(), config_error=ConfigError("not valid TOML"))

    assert cli.main(["test-notification", "--transport", "mail"]) == cli.EXIT_USAGE


def test_an_unknown_severity_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeTransport())

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["test-notification", "--severity", "fatal"])

    assert exit_info.value.code == cli.EXIT_USAGE


def test_an_unknown_transport_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeTransport())

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["test-notification", "--transport", "carrier-pigeon"])

    assert exit_info.value.code == cli.EXIT_USAGE


def test_the_severity_choices_are_the_pve_severities() -> None:
    assert [severity.value for severity in PveSeverity] == cli.SEVERITY_CHOICES


# The matchers (ADR 0020)


def test_the_matchers_that_route_the_test_are_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeTransport(), matchers=recorded("test-cluster-c"))

    cli.main(["test-notification", "--severity", "warning"])

    assert "Matchers:  pve-smart-alert\n" in capsys.readouterr().out


def test_a_test_that_no_matcher_routes_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The matcher left by M1 routes only warning and error (Research 06).
    install(monkeypatch, FakeTransport(), matchers=recorded("test-cluster-a"))

    assert cli.main(["test-notification", "--severity", "info"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "Delivered: yes" in out
    assert "Matchers:  none, no matcher routes this notification to an enabled target\n" in out


def test_the_matchers_follow_the_severity_of_the_test(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeTransport(), matchers=recorded("test-cluster-a"))

    cli.main(["test-notification", "--severity", "error"])

    assert "Matchers:  pve-smart-alert\n" in capsys.readouterr().out


def test_matchers_that_cannot_be_read_are_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeTransport())

    assert cli.main(["test-notification"]) == cli.EXIT_OK

    assert "Matchers:  cannot be read: pvesh is missing at /usr/bin/pvesh\n" in (
        capsys.readouterr().out
    )


def test_a_test_sent_as_mail_is_followed_as_system_mail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The mail forwarder makes a notification of the type system-mail of it
    # (ADR 0022).
    transport = FakeTransport(transport=TransportName.MAIL)
    install(monkeypatch, transport, matchers=recorded("test-cluster-c"))

    cli.main(["test-notification"])

    assert "Matchers:  default-matcher, as system-mail\n" in capsys.readouterr().out


def test_a_test_sent_as_mail_that_no_matcher_routes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # In configuration B the default matcher routes only vzdump (Research 06).
    transport = FakeTransport(transport=TransportName.MAIL)
    install(monkeypatch, transport, matchers=recorded("test-cluster-b"))

    cli.main(["test-notification"])

    assert "Matchers:  none, no matcher routes mail to root to an enabled target\n" in (
        capsys.readouterr().out
    )


def test_mail_that_does_not_reach_the_notification_system_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport(transport=TransportName.MAIL)
    install(monkeypatch, transport, matchers=recorded("test-cluster-c"), forwarded=False)

    cli.main(["test-notification"])

    assert (
        "Matchers:  none, mail to root does not reach the notification system:"
        " /root/.forward has no line for proxmox-mail-forward\n"
    ) in capsys.readouterr().out


def test_a_matcher_that_matches_but_is_disabled_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Configuration B: the matcher of the tool is disabled (Research 06).
    install(monkeypatch, FakeTransport(), matchers=recorded("test-cluster-b"))

    cli.main(["test-notification", "--severity", "warning"])

    assert (
        "Matchers:  none, no matcher routes this notification to an enabled target;"
        " matcher pve-smart-alert matches, but it is disabled\n"
    ) in capsys.readouterr().out


def test_a_test_that_was_not_delivered_has_no_matchers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeTransport(delivered=False), matchers=recorded("test-cluster-c"))

    cli.main(["test-notification"])

    assert "Matchers:" not in capsys.readouterr().out


# The hint about an empty log


HINT = "Nothing logged can also mean that no matcher matched"


def test_a_test_sent_as_mail_gets_no_hint_about_matchers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The mail route never brings an answer of the notification system, and
    # the line Matchers already says where the mail goes.
    transport = FakeTransport(transport=TransportName.MAIL)
    install(monkeypatch, transport, matchers=recorded("test-cluster-c"))

    cli.main(["test-notification", "--transport", "mail"])

    out = capsys.readouterr().out
    assert "Log:\n  (the mail command logged nothing)\n" in out
    assert HINT not in out
    assert "the notification system logged nothing" not in out


def test_a_test_sent_as_mail_without_readable_matchers_gets_no_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeTransport(transport=TransportName.MAIL))

    cli.main(["test-notification"])

    assert HINT not in capsys.readouterr().out


def test_a_routing_that_is_decided_needs_no_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, severity in (("test-cluster-c", "warning"), ("test-cluster-a", "info")):
        install(monkeypatch, FakeTransport(), matchers=recorded(name))

        cli.main(["test-notification", "--severity", severity])

        out = capsys.readouterr().out
        assert "  (the notification system logged nothing)\n" in out
        assert HINT not in out


def test_a_routing_that_cannot_be_decided_keeps_the_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Without pvesh, the empty log is the only clue (ADR 0020).
    install(monkeypatch, FakeTransport())

    cli.main(["test-notification"])

    assert HINT in capsys.readouterr().out


def test_a_test_that_was_not_delivered_gets_no_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeTransport(delivered=False))

    cli.main(["test-notification"])

    assert HINT not in capsys.readouterr().out
