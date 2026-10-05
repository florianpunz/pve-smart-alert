# SPDX-License-Identifier: AGPL-3.0-or-later
"""The routing check: whether the notifications of the tool reach a target.

A notification that no matcher of the notification system matches is accepted
and dropped without an error, and the answer of the notification library does
not tell this apart from a delivery (ADR 0020). This module reads the matchers
and targets through the public API with `pvesh` and evaluates them the way
`proxmox-notify` does (Research 01):

- A matcher combines its rules with its mode, `all` or `any`: first the rules
  of each kind, then the kinds. A matcher without rules matches everything,
  and `invert-match` inverts the result of all others.
- A rule on a field that the notification does not carry does not match.
- A disabled matcher takes no part, and of the targets of a matcher only one
  that exists and is enabled receives the notification.

What cannot be decided here is unknown, and an unknown never counts as
routed: a time rule, a rule on a field whose value differs between
notifications, a regular expression that Python reads differently, a key this
module does not know. The result is a hint; the notification system remains
the authority on what is delivered (ADR 0020).

Only `pvesh` is run, a documented command. No Proxmox VE code is imported
(ADR 0008).
"""

from __future__ import annotations

import json
import re
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, TypeAlias, TypeGuard

from pve_smart_alert.model import (
    FIELD_DEVICE,
    FIELD_EVENT,
    FIELD_HOSTNAME,
    FIELD_MODEL,
    FIELD_SERIAL,
    FIELD_TYPE,
    NOTIFICATION_TYPE,
    PVE_SEVERITY,
    Notification,
    PveSeverity,
)
from pve_smart_alert.paths import PVESH_PATH
from pve_smart_alert.process import ProcessRunner, run_with_timeout

# pvesh loads a large part of the Proxmox VE code on every start; on a healthy
# node it answers within a few seconds.
TIMEOUT_SECONDS: Final = 30.0

MATCHERS: Final = "/cluster/notifications/matchers"
TARGETS: Final = "/cluster/notifications/targets"

# The fields whose values differ from one notification of the tool to the
# next (FR-503). A rule on one of them matches some notifications and not
# others. A field the tool sends in the future belongs here as well, because
# a rule on a field the tool never sends is decided as "no match".
VARYING_FIELDS: Final = frozenset({FIELD_EVENT, FIELD_DEVICE, FIELD_SERIAL, FIELD_MODEL})

# The keys of a matcher as `proxmox-notify` defines it. Another key could
# change what the matcher does, so a matcher that has one is unknown.
MATCHER_KEYS: Final = frozenset(
    {
        "comment",
        "disable",
        "invert-match",
        "match-calendar",
        "match-field",
        "match-severity",
        "mode",
        "name",
        "origin",
        "target",
    }
)

# The severities of `proxmox-notify`. `unknown` is the one of forwarded mail.
SEVERITY_NAMES: Final = frozenset({"info", "notice", "warning", "error", "unknown"})

# True, False, or None for "cannot be decided here". The values are combined
# like Kleene's three-valued logic, so that a decided result never rests on an
# undecided part.
Truth: TypeAlias = bool | None


class RoutingError(Exception):
    """The matchers and targets cannot be read."""


class Verdict(StrEnum):
    """Whether a notification reaches a target."""

    ROUTED = "routed"
    NOT_ROUTED = "not routed"
    # It depends on something this check cannot decide.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Metadata:
    """What the matchers see of a notification: its severity and its fields.

    `varying` names the fields whose value differs between the notifications
    this metadata stands for. A rule on one of them cannot be decided.
    """

    severity: str
    fields: Mapping[str, str]
    varying: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Routing:
    """Where notifications with one set of metadata go.

    `matchers` are the matchers that route them to an enabled target, in the
    order of the configuration. `reasons` say why the verdict is unknown.
    """

    verdict: Verdict
    matchers: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotificationConfig:
    """The matchers and the targets, as the API lists them."""

    matchers: tuple[Mapping[str, object], ...]
    targets: tuple[Mapping[str, object], ...]

    @classmethod
    def from_json(cls, matchers: str, targets: str) -> NotificationConfig:
        """Return the configuration from the two answers of the API.

        Raises `RoutingError` when an answer is not a list of entries.
        """
        return cls(matchers=_entries(matchers, MATCHERS), targets=_entries(targets, TARGETS))


def tool_metadata(severity: PveSeverity, *, node: str) -> Metadata:
    """Return what the matchers see of the notifications of the tool.

    Every notification carries `type` and `hostname` (FR-502); the fields of a
    single drive differ between notifications (FR-503).
    """
    return Metadata(
        severity=severity.value,
        fields={FIELD_TYPE: NOTIFICATION_TYPE, FIELD_HOSTNAME: node},
        varying=VARYING_FIELDS,
    )


def metadata_of(notification: Notification) -> Metadata:
    """Return what the matchers see of one notification, which is all of it."""
    return Metadata(
        severity=PVE_SEVERITY[notification.severity].value,
        fields=notification.fields_for(),
    )


def read_notification_config(
    *,
    pvesh_path: Path = PVESH_PATH,
    runner: ProcessRunner = run_with_timeout,
    timeout: float = TIMEOUT_SECONDS,
) -> NotificationConfig:
    """Read the matchers and the targets through the API.

    Raises `RoutingError` when they cannot be read, for example without
    `pvesh` or without a working cluster file system. That is no error of the
    host, only a check that cannot be done (ADR 0020).
    """
    if not pvesh_path.is_file():
        raise RoutingError(f"pvesh is missing at {pvesh_path}")

    return NotificationConfig.from_json(
        _get(MATCHERS, pvesh_path=pvesh_path, runner=runner, timeout=timeout),
        _get(TARGETS, pvesh_path=pvesh_path, runner=runner, timeout=timeout),
    )


def evaluate(config: NotificationConfig, metadata: Metadata) -> Routing:
    """Return where notifications with this metadata go."""
    enabled_targets = _enabled_targets(config.targets)
    result: Truth = False
    matchers: list[str] = []
    reasons: list[str] = []
    for matcher in config.matchers:
        routes, why = _routes(matcher, metadata, enabled_targets)
        result = _any(result, routes)
        if routes is True:
            matchers.append(_name(matcher))
        elif routes is None:
            reasons.extend(why)

    if result is True:
        return Routing(Verdict.ROUTED, matchers=tuple(matchers))
    if result is None:
        return Routing(Verdict.UNKNOWN, reasons=tuple(dict.fromkeys(reasons)))
    return Routing(Verdict.NOT_ROUTED)


def _get(path: str, *, pvesh_path: Path, runner: ProcessRunner, timeout: float) -> str:
    """Return the answer of the API for one path, as JSON text."""
    try:
        result = runner([pvesh_path, "get", path, "--output-format", "json"], timeout=timeout)
    except OSError as failure:
        raise RoutingError(
            f"pvesh could not be started: {failure.strerror or failure}"
        ) from failure

    if result.timed_out:
        raise RoutingError(f"pvesh get {path} did not answer within {timeout:g} seconds")
    if result.returncode != 0:
        detail = result.lines[-1] if result.lines else ""
        suffix = f": {detail}" if detail else ""
        raise RoutingError(f"pvesh get {path} ended with exit status {result.returncode}{suffix}")
    return result.stdout


def _entries(text: str, path: str) -> tuple[Mapping[str, object], ...]:
    """Return the entries of one answer of the API."""
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as error:
        raise RoutingError(f"the answer for {path} is not JSON") from error
    if not isinstance(answer, list) or not all(isinstance(entry, dict) for entry in answer):
        raise RoutingError(f"the answer for {path} is not a list of entries")
    return tuple(answer)


def _routes(
    matcher: Mapping[str, object],
    metadata: Metadata,
    enabled_targets: Mapping[str, Truth],
) -> tuple[Truth, list[str]]:
    """Return whether one matcher routes the notification to an enabled target.

    The reasons are those of an undecided result.
    """
    disabled = _flag(matcher.get("disable"))
    if disabled is True:
        return False, []

    reasons: list[str] = []
    if disabled is None:
        reasons.append(f"matcher {_name(matcher)}: the value of disable is not understood")
    matches, match_reasons = _matches(matcher, metadata)
    reaches, target_reasons = _reaches(matcher, enabled_targets)
    result = _all(_all(None if disabled is None else True, matches), reaches)
    return result, ([] if result is not None else reasons + match_reasons + target_reasons)


def _matches(matcher: Mapping[str, object], metadata: Metadata) -> tuple[Truth, list[str]]:
    """Return whether the rules of one matcher match the notification."""
    name = _name(matcher)
    unknown_keys = sorted(set(matcher) - MATCHER_KEYS)
    if unknown_keys:
        return None, [
            f"matcher {name} has the key {unknown_keys[0]}, which this check does not know"
        ]

    mode = matcher.get("mode", "all")
    operator = _MODES.get(mode) if isinstance(mode, str) else None
    if operator is None:
        return None, [f"matcher {name} has the mode {mode}, which this check does not know"]
    neutral, combine = operator

    result: Truth = neutral
    reasons: list[str] = []
    has_rules = False
    for key, decide in _RULES:
        rules = matcher.get(key, [])
        if not _is_strings(rules):
            return None, [f"matcher {name}: {key} is not a list of rules"]
        if not rules:
            continue
        has_rules = True
        kind: Truth = neutral
        for rule in rules:
            decided, reason = decide(rule, metadata)
            kind = combine(kind, decided)
            if reason is not None:
                reasons.append(f"matcher {name}: {reason}")
        result = combine(result, kind)

    if not has_rules:
        # A matcher without rules matches everything, inverted or not. This is
        # the built-in default matcher (Research 01).
        return True, []

    invert = _flag(matcher.get("invert-match"))
    if invert is None:
        return None, [f"matcher {name}: the value of invert-match is not understood"]
    if result is None:
        return None, reasons
    return result != invert, []


def _reaches(
    matcher: Mapping[str, object], enabled_targets: Mapping[str, Truth]
) -> tuple[Truth, list[str]]:
    """Return whether one of the targets of a matcher exists and is enabled."""
    targets = matcher.get("target", [])
    if not _is_strings(targets):
        return None, [f"matcher {_name(matcher)}: target is not a list of names"]

    result: Truth = False
    reasons: list[str] = []
    for target in targets:
        # A target that does not exist receives nothing (Research 01).
        enabled = enabled_targets.get(target, False)
        result = _any(result, enabled)
        if enabled is None:
            reasons.append(f"target {target}: the value of disable is not understood")
    return result, ([] if result is not None else reasons)


def _severity_rule(rule: str, metadata: Metadata) -> tuple[Truth, str | None]:
    """Decide one `match-severity` rule: severities separated by commas."""
    severities = {part.strip() for part in rule.split(",")}
    if not severities <= SEVERITY_NAMES:
        return None, f"the severity rule {rule} names a severity this check does not know"
    return metadata.severity in severities, None


def _field_rule(rule: str, metadata: Metadata) -> tuple[Truth, str | None]:
    """Decide one `match-field` rule: `exact:FIELD=VALUES` or `regex:FIELD=EXPRESSION`."""
    kind, colon, rest = rule.partition(":")
    field, equals, expected = rest.partition("=")
    if kind not in ("exact", "regex") or not colon or not equals or not field:
        return None, f"the field rule {rule} cannot be read"
    if field in metadata.varying:
        return None, f"the rule {rule} depends on {field}, which differs between notifications"

    value = metadata.fields.get(field)
    if value is None:
        # A rule on a field the notification does not carry does not match.
        return False, None
    if kind == "exact":
        return value in {part.strip() for part in expected.split(",")}, None

    pattern = _compile(expected)
    if pattern is None:
        return None, f"the regular expression of the rule {rule} cannot be evaluated here"
    return pattern.search(value) is not None, None


def _calendar_rule(rule: str, _metadata: Metadata) -> tuple[Truth, str | None]:
    """Decide one `match-calendar` rule, which is not possible here."""
    # The rule compares the time a notification is sent, so whether a future
    # notification is routed depends on when it comes.
    return None, f"the time rule {rule} makes the routing depend on the time"


_Decide: TypeAlias = Callable[[str, Metadata], tuple[Truth, str | None]]

# The kinds of rules, in the order `proxmox-notify` combines them. The order
# does not change a result.
_RULES: Final[tuple[tuple[str, _Decide], ...]] = (
    ("match-severity", _severity_rule),
    ("match-field", _field_rule),
    ("match-calendar", _calendar_rule),
)


def _all(left: Truth, right: Truth) -> Truth:
    """Both, in three-valued logic."""
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


def _any(left: Truth, right: Truth) -> Truth:
    """Either, in three-valued logic."""
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


# The modes of a matcher: the value to start from and the way to combine.
_MODES: Final[Mapping[str, tuple[Truth, Callable[[Truth, Truth], Truth]]]] = {
    "all": (True, _all),
    "any": (False, _any),
}


def _compile(expression: str) -> re.Pattern[str] | None:
    """Return a regular expression of a rule, or `None`.

    `proxmox-notify` uses the regular expressions of Rust, which Python reads
    alike in the common cases. An expression that Python cannot compile, or
    compiles only with a warning that it may mean something else, such as a
    nested character class, is not evaluated.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            return re.compile(expression)
        except (re.error, Warning):
            return None


def _enabled_targets(targets: Sequence[Mapping[str, object]]) -> dict[str, Truth]:
    """Return for each target whether it is enabled."""
    enabled: dict[str, Truth] = {}
    for target in targets:
        name = target.get("name")
        if isinstance(name, str):
            disabled = _flag(target.get("disable"))
            enabled[name] = None if disabled is None else not disabled
    return enabled


def _flag(value: object) -> Truth:
    """Return a flag of the API, or `None` when its value is not understood.

    The API writes a set flag as 1 and leaves out one that is not set
    (Research 06).
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    return None


def _is_strings(value: object) -> TypeGuard[list[str]]:
    """Whether a value is a list of strings, as the API writes rules and targets."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _name(matcher: Mapping[str, object]) -> str:
    """Return the name of a matcher, as it is shown."""
    name = matcher.get("name")
    return name if isinstance(name, str) else "(without a name)"
