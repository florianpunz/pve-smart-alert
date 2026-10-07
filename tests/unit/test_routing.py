# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the routing check (ADR 0020).

The recorded configurations come from the test cluster (Research 06); the
built-in one is derived from the default configuration of Proxmox VE. Every
rule of the evaluation, which follows `proxmox-notify` (Research 01), has a
test with a constructed matcher. No test needs `pvesh`: the process runner is
a parameter (ADR 0016).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from pve_smart_alert.model import PveSeverity, Severity
from pve_smart_alert.process import ProcessResult
from pve_smart_alert.render import render_test_notification
from pve_smart_alert.routing import (
    MATCHERS,
    TARGETS,
    TIMEOUT_SECONDS,
    VARYING_FIELDS,
    Blocked,
    Metadata,
    NotificationConfig,
    Routing,
    RoutingError,
    Verdict,
    evaluate,
    forwarded_mail_metadata,
    mail_is_forwarded,
    metadata_of,
    read_notification_config,
    tool_metadata,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pvesh"
NODE = "pve7"


def recorded(name: str) -> NotificationConfig:
    """Return one configuration of `tests/fixtures/pvesh`."""
    directory = FIXTURES / name
    return NotificationConfig.from_json(
        (directory / "matchers.json").read_text(encoding="utf-8"),
        (directory / "targets.json").read_text(encoding="utf-8"),
    )


def matcher(name: str = "test", **keys: object) -> dict[str, object]:
    """Return a matcher that routes to the target `relay`, with these keys.

    Keys are written with underscores and become the dashed keys of the API.
    """
    entry: dict[str, object] = {"name": name, "mode": "all", "target": ["relay"]}
    entry.update({key.replace("_", "-"): value for key, value in keys.items()})
    return entry


def config(
    *matchers: dict[str, object], targets: Sequence[dict[str, object]] | None = None
) -> NotificationConfig:
    """Return a configuration with these matchers and an enabled target `relay`."""
    if targets is None:
        targets = [{"name": "relay", "origin": "user-created", "type": "smtp"}]
    return NotificationConfig(matchers=tuple(matchers), targets=tuple(targets))


def routing(
    configuration: NotificationConfig, severity: PveSeverity = PveSeverity.WARNING
) -> Routing:
    """Return where a notification of the tool with this severity goes."""
    return evaluate(configuration, tool_metadata(severity, node=NODE))


def verdict(
    configuration: NotificationConfig, severity: PveSeverity = PveSeverity.WARNING
) -> Verdict:
    return routing(configuration, severity).verdict


# The recorded configurations


@pytest.mark.parametrize(
    ("name", "routed"),
    [
        # A: the matcher of the tool routes only warning and error.
        ("test-cluster-a", {PveSeverity.WARNING, PveSeverity.ERROR}),
        # B: the matcher of the tool is disabled, the default matcher
        # routes only vzdump.
        ("test-cluster-b", set()),
        # C: the matcher of the tool routes all four severities.
        ("test-cluster-c", set(PveSeverity)),
        # Unchanged: the default matcher has no rules.
        ("builtin-default", set(PveSeverity)),
    ],
)
def test_the_recorded_configurations(name: str, routed: set[PveSeverity]) -> None:
    configuration = recorded(name)

    for severity in PveSeverity:
        expected = Verdict.ROUTED if severity in routed else Verdict.NOT_ROUTED
        assert verdict(configuration, severity) is expected, severity


def test_the_matchers_that_route_are_named() -> None:
    assert routing(recorded("test-cluster-c")) == Routing(
        Verdict.ROUTED, matchers=("pve-smart-alert",)
    )
    assert routing(recorded("builtin-default")) == Routing(
        Verdict.ROUTED, matchers=("default-matcher",)
    )


def test_mail_to_root_depends_on_the_default_matcher() -> None:
    # Mail to root arrives as system-mail with the severity unknown
    # (Research 01). In configuration B it is dropped as well, so the
    # fallback route of the tool would be silent too.
    forwarded = Metadata(severity="unknown", fields={"type": "system-mail", "hostname": NODE})

    assert evaluate(recorded("test-cluster-a"), forwarded) == Routing(
        Verdict.ROUTED, matchers=("default-matcher",)
    )
    assert evaluate(recorded("test-cluster-b"), forwarded).verdict is Verdict.NOT_ROUTED


# The rules of proxmox-notify (Research 01)


@pytest.mark.parametrize("severity", list(PveSeverity))
def test_a_matcher_without_rules_matches_everything(severity: PveSeverity) -> None:
    assert verdict(config(matcher()), severity) is Verdict.ROUTED


def test_a_matcher_without_rules_matches_even_when_inverted() -> None:
    assert verdict(config(matcher(invert_match=1))) is Verdict.ROUTED


def test_mode_all_needs_every_rule() -> None:
    configuration = config(
        matcher(match_severity=["warning,error"], match_field=["regex:type=^pve-smart-alert$"])
    )

    assert verdict(configuration, PveSeverity.WARNING) is Verdict.ROUTED
    assert verdict(configuration, PveSeverity.INFO) is Verdict.NOT_ROUTED


def test_mode_any_needs_one_rule() -> None:
    configuration = config(
        matcher(mode="any", match_severity=["error"], match_field=["exact:type=vzdump"])
    )

    assert verdict(configuration, PveSeverity.ERROR) is Verdict.ROUTED
    assert verdict(configuration, PveSeverity.INFO) is Verdict.NOT_ROUTED


def test_the_mode_combines_the_rules_of_one_kind_as_well() -> None:
    every = config(matcher(match_severity=["info", "warning"]))
    either = config(matcher(mode="any", match_severity=["info", "warning"]))

    # No notification has two severities.
    assert verdict(every, PveSeverity.INFO) is Verdict.NOT_ROUTED
    assert verdict(either, PveSeverity.INFO) is Verdict.ROUTED
    assert verdict(either, PveSeverity.NOTICE) is Verdict.NOT_ROUTED


def test_the_mode_is_all_when_it_is_left_out() -> None:
    entry = matcher(match_severity=["error"], match_field=["exact:type=vzdump"])
    del entry["mode"]

    assert verdict(config(entry), PveSeverity.ERROR) is Verdict.NOT_ROUTED


def test_a_severity_rule_lists_severities_separated_by_commas() -> None:
    configuration = config(matcher(match_severity=["info, warning"]))

    assert verdict(configuration, PveSeverity.WARNING) is Verdict.ROUTED
    assert verdict(configuration, PveSeverity.ERROR) is Verdict.NOT_ROUTED


def test_an_exact_rule_lists_values_separated_by_commas() -> None:
    assert verdict(config(matcher(match_field=["exact:type=vzdump, pve-smart-alert"]))) is (
        Verdict.ROUTED
    )


def test_an_exact_rule_compares_whole_values() -> None:
    assert verdict(config(matcher(match_field=["exact:type=pve-smart"]))) is Verdict.NOT_ROUTED


def test_a_regex_rule_matches_anywhere_in_the_value() -> None:
    assert verdict(config(matcher(match_field=["regex:type=smart"]))) is Verdict.ROUTED
    assert verdict(config(matcher(match_field=["regex:type=^smart"]))) is Verdict.NOT_ROUTED


def test_the_hostname_is_the_node() -> None:
    assert verdict(config(matcher(match_field=["exact:hostname=pve7"]))) is Verdict.ROUTED
    assert verdict(config(matcher(match_field=["exact:hostname=pve5"]))) is Verdict.NOT_ROUTED


def test_a_rule_on_a_field_the_tool_does_not_send_does_not_match() -> None:
    assert verdict(config(matcher(match_field=["exact:job-id=backup-1"]))) is Verdict.NOT_ROUTED


def test_invert_match_inverts_the_rules() -> None:
    other_types = config(matcher(match_field=["exact:type=vzdump"], invert_match=1))
    this_type = config(matcher(match_field=["exact:type=pve-smart-alert"], invert_match=1))

    assert verdict(other_types) is Verdict.ROUTED
    assert verdict(this_type) is Verdict.NOT_ROUTED


def test_a_disabled_matcher_takes_no_part() -> None:
    assert verdict(config(matcher(disable=1))) is Verdict.NOT_ROUTED


def test_a_disabled_target_receives_nothing() -> None:
    targets = [{"disable": 1, "name": "relay", "type": "smtp"}]

    assert verdict(config(matcher(), targets=targets)) is Verdict.NOT_ROUTED


def test_a_target_that_does_not_exist_receives_nothing() -> None:
    assert verdict(config(matcher(target=["absent"]))) is Verdict.NOT_ROUTED


def test_a_matcher_without_targets_routes_nothing() -> None:
    assert verdict(config(matcher(target=[]))) is Verdict.NOT_ROUTED


def test_one_enabled_target_is_enough() -> None:
    targets: list[dict[str, object]] = [
        {"name": "relay", "type": "smtp"},
        {"disable": 1, "name": "off", "type": "smtp"},
    ]

    assert verdict(config(matcher(target=["off", "relay"]), targets=targets)) is Verdict.ROUTED


def test_every_matcher_that_routes_is_named() -> None:
    configuration = config(matcher("first"), matcher("off", disable=1), matcher("second"))

    assert routing(configuration).matchers == ("first", "second")


# What cannot be decided


def test_a_rule_on_a_field_that_differs_between_notifications_is_undecided() -> None:
    result = routing(config(matcher(match_field=["exact:event=problem"])))

    assert result.verdict is Verdict.UNKNOWN
    assert result.reasons == (
        "matcher test: the rule exact:event=problem depends on event,"
        " which differs between notifications",
    )


def test_a_time_rule_is_undecided() -> None:
    result = routing(config(matcher(match_calendar=["mon..fri 8-17"])))

    assert result.verdict is Verdict.UNKNOWN
    assert "time rule mon..fri 8-17" in result.reasons[0]


def test_a_decided_rule_is_not_hidden_by_an_undecided_one() -> None:
    every = config(matcher(match_severity=["error"], match_calendar=["mon..fri 8-17"]))
    either = config(matcher(mode="any", match_severity=["error"], match_calendar=["mon"]))

    assert verdict(every, PveSeverity.INFO) is Verdict.NOT_ROUTED
    assert verdict(every, PveSeverity.ERROR) is Verdict.UNKNOWN
    assert verdict(either, PveSeverity.ERROR) is Verdict.ROUTED
    assert verdict(either, PveSeverity.INFO) is Verdict.UNKNOWN


def test_another_matcher_can_decide() -> None:
    configuration = config(matcher("office-hours", match_calendar=["mon..fri 8-17"]), matcher())

    assert routing(configuration) == Routing(Verdict.ROUTED, matchers=("test",))


def test_an_undecided_matcher_without_an_enabled_target_routes_nothing() -> None:
    targets = [{"disable": 1, "name": "relay", "type": "smtp"}]
    configuration = config(matcher(match_calendar=["mon..fri 8-17"]), targets=targets)

    assert verdict(configuration) is Verdict.NOT_ROUTED


def test_an_unknown_key_is_undecided() -> None:
    result = routing(config(matcher(match_mood=["calm"])))

    assert result.verdict is Verdict.UNKNOWN
    assert result.reasons == (
        "matcher test has the key match-mood, which this check does not know",
    )


def test_an_unknown_mode_is_undecided() -> None:
    assert verdict(config(matcher(mode="most", match_severity=["warning"]))) is Verdict.UNKNOWN


@pytest.mark.parametrize(
    "rule",
    [
        # Unicode classes of Rust, which Python does not compile.
        r"regex:type=^\p{L}",
        # A class of Rust that Python reads as a nested set, with a warning.
        "regex:type=[[:alpha:]-]+",
    ],
)
def test_a_regex_that_python_reads_differently_is_undecided(rule: str) -> None:
    result = routing(config(matcher(match_field=[rule])))

    assert result.verdict is Verdict.UNKNOWN
    assert "cannot be evaluated here" in result.reasons[0]


@pytest.mark.parametrize(
    "rule",
    [
        "type=pve-smart-alert",
        "contains:type=pve-smart-alert",
        "exact:type",
    ],
)
def test_a_field_rule_that_cannot_be_read_is_undecided(rule: str) -> None:
    assert verdict(config(matcher(match_field=[rule]))) is Verdict.UNKNOWN


def test_an_unknown_severity_is_undecided() -> None:
    assert verdict(config(matcher(match_severity=["warning,fatal"]))) is Verdict.UNKNOWN


def test_rules_that_are_not_a_list_are_undecided() -> None:
    assert verdict(config(matcher(match_severity="warning"))) is Verdict.UNKNOWN


@pytest.mark.parametrize("value", ["yes", 2])
def test_a_flag_that_is_not_understood_is_undecided(value: object) -> None:
    on_the_target = [{"disable": value, "name": "relay", "type": "smtp"}]

    assert verdict(config(matcher(disable=value))) is Verdict.UNKNOWN
    assert verdict(config(matcher(invert_match=value, match_severity=["error"]))) is (
        Verdict.UNKNOWN
    )
    assert verdict(config(matcher(), targets=on_the_target)) is Verdict.UNKNOWN


def test_a_flag_can_be_written_as_a_boolean() -> None:
    assert verdict(config(matcher(disable=True))) is Verdict.NOT_ROUTED
    assert verdict(config(matcher(disable=False))) is Verdict.ROUTED


# What the matchers see


def test_the_notifications_of_the_tool() -> None:
    metadata = tool_metadata(PveSeverity.ERROR, node=NODE)

    assert metadata == Metadata(
        severity="error",
        fields={"type": "pve-smart-alert", "hostname": NODE},
        varying=VARYING_FIELDS,
    )
    # The fields of a single drive (FR-503).
    assert {"event", "device", "serial", "model"} <= VARYING_FIELDS


def test_a_single_notification_is_seen_completely() -> None:
    notification = render_test_notification(Severity.CRITICAL, node=NODE)

    metadata = metadata_of(notification)

    assert metadata == Metadata(
        severity="error",
        fields={"event": "test", "type": "pve-smart-alert", "hostname": NODE},
    )
    # Its event is known, so a rule on it is decided.
    configuration = config(matcher(match_field=["exact:event=test"]))
    assert evaluate(configuration, metadata).verdict is Verdict.ROUTED


# Matchers that match but route nowhere


def test_a_disabled_matcher_whose_rules_match_is_named() -> None:
    result = routing(config(matcher("tool", disable=1)))

    assert result == Routing(Verdict.NOT_ROUTED, blocked=(Blocked("tool", "it is disabled"),))
    assert (
        result.blocked[0].describe("warning") == "matcher tool matches warning, but it is disabled"
    )
    assert result.blocked[0].describe() == "matcher tool matches, but it is disabled"


def test_a_disabled_matcher_whose_rules_do_not_match_is_not_named() -> None:
    configuration = config(matcher("tool", disable=1, match_severity=["error"]))

    assert routing(configuration, PveSeverity.INFO).blocked == ()
    assert routing(configuration, PveSeverity.ERROR).blocked == (Blocked("tool", "it is disabled"),)


@pytest.mark.parametrize(
    ("targets", "reason"),
    [
        (["relay"], "its target relay is disabled"),
        (["absent"], "its target absent does not exist"),
        ([], "it has no target"),
        (["relay", "absent"], "of its targets, relay is disabled, absent does not exist"),
    ],
)
def test_a_matcher_without_an_enabled_target_is_named(targets: list[str], reason: str) -> None:
    disabled_relay = [{"disable": 1, "name": "relay", "type": "smtp"}]

    result = routing(config(matcher("tool", target=targets), targets=disabled_relay))

    assert result.blocked == (Blocked("tool", reason),)


def test_nothing_is_named_when_the_notification_is_routed() -> None:
    configuration = config(matcher("off", disable=1), matcher("on"))

    assert routing(configuration) == Routing(Verdict.ROUTED, matchers=("on",))


# The fallback route: mail to root (ADR 0022)


def test_mail_to_root_is_seen_as_system_mail() -> None:
    # The metadata the mail forwarder sets for every mail (Research 01).
    assert forwarded_mail_metadata(node=NODE) == Metadata(
        severity="unknown", fields={"type": "system-mail", "hostname": NODE}
    )


@pytest.mark.parametrize(
    ("content", "forwarded"),
    [
        # What the package proxmox-mail-forward writes (Research 01).
        ("|/usr/libexec/proxmox-mail-forward\n", True),
        ('"|/usr/libexec/proxmox-mail-forward"\n', True),
        ("admin@example.com\n|/usr/libexec/proxmox-mail-forward\n", True),
        ("admin@example.com\n", False),
        ("# |/usr/libexec/proxmox-mail-forward\n", False),
        ("", False),
    ],
)
def test_mail_reaches_the_forwarder_through_the_forward_file(
    tmp_path: Path, content: str, forwarded: bool
) -> None:
    path = tmp_path / "forward"
    path.write_text(content, encoding="utf-8")

    assert mail_is_forwarded(path) is forwarded


def test_without_a_forward_file_mail_stays_in_the_mailbox(tmp_path: Path) -> None:
    assert mail_is_forwarded(tmp_path / "forward") is False


def test_a_forward_file_that_cannot_be_read_is_undecided(tmp_path: Path) -> None:
    # A directory stands for a file this process may not read.
    assert mail_is_forwarded(tmp_path) is None


# Reading through pvesh


class PveshRunner:
    """Answers the calls of pvesh with fixed results and records them."""

    def __init__(
        self,
        answers: Sequence[ProcessResult] = (),
        *,
        directory: Path | None = None,
        failure: OSError | None = None,
    ) -> None:
        self.answers = list(answers)
        self.directory = directory
        self.failure = failure
        self.calls: list[tuple[list[str], str | None, float]] = []

    def __call__(
        self,
        command: Sequence[str | Path],
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> ProcessResult:
        self.calls.append(([str(argument) for argument in command], input_text, timeout))
        if self.failure is not None:
            raise self.failure
        if self.directory is not None:
            name = str(command[2]).rsplit("/", 1)[-1]
            text = (self.directory / f"{name}.json").read_text(encoding="utf-8")
            return ProcessResult(returncode=0, stdout=text, stderr="", timed_out=False)
        return self.answers.pop(0)


@pytest.fixture
def pvesh(tmp_path: Path) -> Path:
    """A file where pvesh is expected."""
    path = tmp_path / "pvesh"
    path.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def answer(stdout: str) -> ProcessResult:
    return ProcessResult(returncode=0, stdout=stdout, stderr="", timed_out=False)


def test_the_matchers_and_targets_are_read_through_the_api(pvesh: Path) -> None:
    runner = PveshRunner(directory=FIXTURES / "test-cluster-c")

    configuration = read_notification_config(pvesh_path=pvesh, runner=runner)

    assert configuration == recorded("test-cluster-c")
    assert runner.calls == [
        ([str(pvesh), "get", MATCHERS, "--output-format", "json"], None, TIMEOUT_SECONDS),
        ([str(pvesh), "get", TARGETS, "--output-format", "json"], None, TIMEOUT_SECONDS),
    ]


def test_without_pvesh_nothing_is_run(tmp_path: Path) -> None:
    runner = PveshRunner()

    with pytest.raises(RoutingError, match="pvesh is missing at"):
        read_notification_config(pvesh_path=tmp_path / "pvesh", runner=runner)

    assert runner.calls == []


def test_pvesh_that_cannot_be_started(pvesh: Path) -> None:
    runner = PveshRunner(failure=PermissionError(13, "Permission denied"))

    with pytest.raises(RoutingError, match="could not be started: Permission denied"):
        read_notification_config(pvesh_path=pvesh, runner=runner)


def test_pvesh_that_ends_with_an_error(pvesh: Path) -> None:
    runner = PveshRunner([ProcessResult(255, "", "first line\nan error of pvesh\n", False)])

    with pytest.raises(RoutingError) as error:
        read_notification_config(pvesh_path=pvesh, runner=runner)

    assert str(error.value) == (
        f"pvesh get {MATCHERS} ended with exit status 255: an error of pvesh"
    )


def test_pvesh_that_does_not_answer(pvesh: Path) -> None:
    runner = PveshRunner([ProcessResult(None, "", "", True)])

    with pytest.raises(RoutingError, match="did not answer within 30 seconds"):
        read_notification_config(pvesh_path=pvesh, runner=runner)


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("pvesh: unknown option\n", "is not JSON"),
        ('{"data": []}', "is not a list of entries"),
        ('["default-matcher"]', "is not a list of entries"),
    ],
)
def test_an_answer_that_is_not_a_list_of_entries(pvesh: Path, stdout: str, message: str) -> None:
    runner = PveshRunner([answer(stdout), answer("[]")])

    with pytest.raises(RoutingError, match=message):
        read_notification_config(pvesh_path=pvesh, runner=runner)
