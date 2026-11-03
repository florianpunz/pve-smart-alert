# SPDX-License-Identifier: AGPL-3.0-or-later
"""The report of `pve-smart-alert config show` (FR-407).

Every key of the effective configuration with its value and origin: the file,
the built-in default or the last good configuration. The per-class thresholds
are shown per class; the per-drive overrides are listed as configured, since
which one applies is known only for a concrete drive.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Final

from pve_smart_alert.checks import CATALOG, Check
from pve_smart_alert.config import (
    TOOL_CHECK_IDS,
    Config,
    ConfigError,
    effective_check,
    tool_conditions_enabled,
)
from pve_smart_alert.model import toml_string

# The words after a value that say where it comes from.
_FROM_FILE: Final = "file"
_FROM_DEFAULT: Final = "default"
_FROM_LAST_GOOD: Final = "last good"

# The severities of a threshold, in the order they are shown.
_SEVERITIES: Final = ("notice", "warning", "critical")

# The drive classes, in the order they are shown.
_CLASS_ORDER: Final = {"hdd": 0, "ssd": 1, "nvme": 2}


def render(
    config: Config,
    raw: Mapping[str, object] | None,
    *,
    error: ConfigError | None = None,
    last_good: bool = False,
) -> list[str]:
    """Return the lines of the report.

    `raw` decides the origin of each value; `error` names a file that could
    not be used. `last_good` credits every value to the last good
    configuration, while the per-drive overrides carry no origin.
    """
    document = raw if raw is not None else {}
    origin = _FROM_LAST_GOOD if last_good else None
    lines = ["effective configuration of this host"]
    source = config.source
    if last_good:
        assert source is not None, "the last good configuration has a source"
        lines.append(
            f"file:      {source}"
            " (the last good configuration; the configuration file could not be used)"
        )
    else:
        lines.append(
            f"file:      {source if source is not None else 'none, the built-in defaults apply'}"
        )
    if error is not None:
        lines.append(f"warning:   {error}")
    lines.extend(_settings(config, document, origin=origin))
    lines.extend(_checks(config, document, origin=origin))
    lines.extend(_drives(config))
    return lines


def _settings(
    config: Config, document: Mapping[str, object], *, origin: str | None = None
) -> list[str]:
    """Return the lines of `[notify]`, `[smartctl]` and `[discovery]`."""
    _origin = _origin_for(origin)
    lines = ["", "[notify]"]
    notify = config.notify
    section = _table_of(document.get("notify"))
    lines.append(_line("transport", f'"{notify.transport.value}"', _origin(section, "transport")))
    for key, value in (
        ("max_drive_notifications", str(notify.max_drive_notifications)),
        ("recovery", _boolean(notify.recovery)),
        ("first_run_summary", _boolean(notify.first_run_summary)),
        ("worsening_cooldown", f'"{_interval(notify.worsening_cooldown)}"'),
        ("event_cooldown", f'"{_interval(notify.event_cooldown)}"'),
        ("clear_runs", str(notify.clear_runs)),
        ("missing_runs", str(notify.missing_runs)),
        ("unreadable_runs", str(notify.unreadable_runs)),
    ):
        lines.append(_line(key, value, _origin(section, key)))
    reminder = _table_of(section.get("reminder"))
    lines.extend(("", "[notify.reminder]"))
    for severity in ("critical", "warning", "notice"):
        lines.append(
            _line(
                severity,
                f'"{_interval(notify.reminder.interval(severity))}"',
                _origin(reminder, severity),
            )
        )

    smartctl = config.smartctl
    section = _table_of(document.get("smartctl"))
    lines.extend(("", "[smartctl]"))
    lines.append(_line("path", f'"{smartctl.path}"', _origin(section, "path")))
    lines.append(
        _line("timeout", f'"{_duration(smartctl.timeout_seconds)}"', _origin(section, "timeout"))
    )
    lines.append(_line("detail", f'"{smartctl.detail.value}"', _origin(section, "detail")))

    discovery = config.discovery
    section = _table_of(document.get("discovery"))
    lines.extend(("", "[discovery]"))
    devices = "; ".join(f"{device.name} [{device.type}]" for device in discovery.devices)
    lines.append(_line("device", devices or "[]", _origin(section, "device")))
    exclude = "; ".join(rule.describe() for rule in discovery.exclude)
    lines.append(_line("exclude", exclude or "[]", _origin(section, "exclude")))
    lines.append(
        _line("probe_cciss", _boolean(discovery.probe_cciss), _origin(section, "probe_cciss"))
    )
    return lines


def _checks(
    config: Config, document: Mapping[str, object], *, origin: str | None = None
) -> list[str]:
    """Return the lines of the checks, each with its effective settings."""
    _origin = _origin_for(origin)
    file_checks = _table_of(document.get("checks"))
    lines = ["", "[checks]"]
    for check in CATALOG.values():
        raw_check = _table_of(file_checks.get(check.id))
        item = effective_check(config, check, None)
        parts = [_value("enabled", str(item.enabled).lower(), _origin(raw_check, "enabled"))]
        if check.per_class is not None:
            parts.extend(_per_class(config, check, raw_check, origin=origin))
        else:
            parts.extend(_single(config, check, raw_check, origin=origin))
        if "confirm_runs" in check.settable:
            parts.append(
                _value("confirm_runs", str(item.confirm_runs), _origin(raw_check, "confirm_runs"))
            )
        lines.append(f'  "{check.id}"  ' + ", ".join(parts))
    lines.extend(_tool_checks(config, file_checks, origin=origin))
    return lines


def _tool_checks(
    config: Config, file_checks: Mapping[str, object], *, origin: str | None = None
) -> list[str]:
    """Return the lines of the conditions of the tool (FR-408, ADR 0031).

    A condition of the tool has a fixed severity and takes no threshold, so
    one line per condition, with its enabled state.
    """
    _origin = _origin_for(origin)
    enabled = tool_conditions_enabled(config)
    lines: list[str] = []
    for name in sorted(TOOL_CHECK_IDS):
        raw_check = _table_of(file_checks.get(name))
        state = _boolean(name in enabled)
        lines.append(f'  "{name}"  ' + _value("enabled", state, _origin(raw_check, "enabled")))
    return lines


def _per_class(
    config: Config, check: Check, raw_check: Mapping[str, object], *, origin: str | None = None
) -> list[str]:
    """Return the thresholds of the one check that differs per drive class."""
    _origin = _origin_for(origin)
    items = {
        drive_class: effective_check(config, check, drive_class) for drive_class in check.classes
    }
    parts = []
    for severity in _SEVERITIES:
        values = []
        for drive_class in sorted(items, key=lambda name: _CLASS_ORDER[name.value]):
            item = items[drive_class]
            value = getattr(item.thresholds, severity, None) if item.thresholds else None
            if value is not None:
                values.append(f"{drive_class.value} {value}")
        if values:
            parts.append(_value(severity, ", ".join(values), _origin(raw_check, severity)))
    return parts


def _single(
    config: Config, check: Check, raw_check: Mapping[str, object], *, origin: str | None = None
) -> list[str]:
    """Return the thresholds of a check with one value for every class."""
    _origin = _origin_for(origin)
    if not check.slots - {"enabled"}:
        # A flag check has no thresholds.
        return []
    item = effective_check(config, check, next(iter(check.classes)) if check.classes else None)
    if item.thresholds is None:
        return []
    parts = []
    for severity in _SEVERITIES:
        value = getattr(item.thresholds, severity)
        if value is not None:
            parts.append(_value(severity, str(value), _origin(raw_check, severity)))
    return parts


def _drives(config: Config) -> list[str]:
    """Return the lines of the per-drive overrides, as they are configured."""
    if not config.drives:
        return ["", "[[drive]]  none"]
    lines: list[str] = []
    for number, drive in enumerate(config.drives, 1):
        lines.append("")
        lines.append(f"[[drive]] {number}")
        lines.append(f"  {drive.selector.describe()}")
        if drive.comment is not None:
            lines.append(f"  comment = {toml_string(drive.comment)}")
        lines.append(f"  exclude = {'true' if drive.exclude else 'false'}")
        if drive.detail is not None:
            lines.append(f'  detail = "{drive.detail.value}"')
        for name, override in drive.checks.items():
            parts = []
            if override.enabled is not None:
                parts.append(f"enabled = {'true' if override.enabled else 'false'}")
            for severity in _SEVERITIES:
                value = getattr(override, severity)
                if value is not None:
                    parts.append(f"{severity} = {_number_or_table(value)}")
            if override.confirm_runs is not None:
                parts.append(f"confirm_runs = {override.confirm_runs}")
            lines.append(f'  checks."{name}"  ' + (", ".join(parts) or "nothing"))
    return lines


def _line(key: str, value: str, origin: str) -> str:
    """Return one line of a section. The keys line up."""
    entry = f"{key} = {value}"
    return f"  {entry:<56} ({origin})"


def _value(key: str, value: str, origin: str) -> str:
    return f"{key} = {value} ({origin})"


def _number_or_table(value: int | Mapping[str, int]) -> str:
    if isinstance(value, Mapping):
        inner = ", ".join(f"{name} = {number}" for name, number in value.items())
        return "{ " + inner + " }"
    return str(value)


def _boolean(value: bool) -> str:
    return "true" if value else "false"


def _interval(value: timedelta | None) -> str:
    """Return an interval as the configuration writes it, "never" for none."""
    return "never" if value is None else _duration(value.total_seconds())


def _origin_for(origin: str | None) -> Callable[[Mapping[str, object], str], str]:
    """Return the function that names where a value comes from.

    With `origin`, every value that carries an origin is credited to it,
    which is how the report shows the last good configuration: no such
    value comes from the file.
    """

    def origin_of(section: Mapping[str, object], key: str) -> str:
        if origin is not None:
            return origin
        return _FROM_FILE if key in section else _FROM_DEFAULT

    return origin_of


def _table_of(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _duration(seconds: float) -> str:
    """Return a duration as the configuration writes it, such as "30s"."""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"
