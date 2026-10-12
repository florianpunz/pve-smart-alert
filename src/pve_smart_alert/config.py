# SPDX-License-Identifier: AGPL-3.0-or-later
"""Loading and validation of the configuration file.

The file is `/etc/pve-smart-alert/config.toml`, its format and its failure
behavior are described in ADR 0011 and ARCHITECTURE.md section 8.

This module reads the keys that are implemented: `[notify] transport`,
`[smartctl]` with `path`, `timeout` and `detail`, the manual devices of
`[[discovery.device]]`, the exclude rules of `[discovery]`, the global
overrides of `[checks."<check-id>"]` and the per-drive overrides of
`[[drive]]`, which can exclude a drive, set its smartctl detail level and
override any check for it. The validation is strict: an unknown section, an
unknown key, a wrong type and a value out of range are errors that name the
place (FR-405). An override that repeats the built-in default is dropped, so
that the reference file, which lists every key with its default, changes
nothing when it is loaded.

An invalid file never stops a run: `load_effective` returns the last
configuration that passed validation, saved as `last-good-config.json` by
`save_last_good`, or the built-in defaults when there is none, together with
the error (FR-406). What a run then uses is `effective_checks`: the built-in
defaults of the catalog, overridden by the global configuration, overridden
by the first matching per-drive override (ARCHITECTURE.md section 6).
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from pve_smart_alert.checks import (
    CATALOG,
    Check,
    EffectiveCheck,
    Thresholds,
    default_checks,
)
from pve_smart_alert.model import DriveClass, DriveIdentity
from pve_smart_alert.paths import CONFIG_PATH, LAST_GOOD_CONFIG_PATH, SMARTCTL_PATH


class TransportName(StrEnum):
    """The values of `notify.transport` (ADR 0008, FR-506)."""

    AUTO = "auto"
    PVE_NOTIFY = "pve-notify"
    MAIL = "mail"


class Detail(StrEnum):
    """The values of `smartctl.detail` (ADR 0004)."""

    # smartctl --xall, with the device statistics and the SCT data.
    EXTENDED = "extended"
    # smartctl --all, for hardware that reacts badly to the extended logs.
    BASIC = "basic"


_TRANSPORT_VALUES: Final = tuple(item.value for item in TransportName)
_DETAIL_VALUES: Final = tuple(item.value for item in Detail)

# Which sections and keys this version knows. Anything else is an error
# (ADR 0011). The table grows with the sections that are implemented. The
# sections `checks` and `drive` are validated by their own builders, because
# the keys of `checks` are the identifiers of the catalog and `drive` is a
# list of tables.
_SCHEMA: Final[Mapping[str, frozenset[str]]] = {
    "notify": frozenset({"transport"}),
    "smartctl": frozenset({"path", "timeout", "detail"}),
    "discovery": frozenset({"device", "exclude"}),
}
_DYNAMIC_SECTIONS: Final = ("checks", "drive")

# The keys of a table that overrides one check (ADR 0011).
_CHECK_KEYS: Final = ("enabled", "notice", "warning", "critical")

# The names of the drive classes, as the configuration writes them.
_CLASS_NAMES: Final = tuple(item.value for item in DriveClass)

# The keys of one `[[drive]]` entry: one selector (ADR 0024), a comment, the
# exclusion, the smartctl detail level and the check overrides (FR-403).
_DRIVE_KEYS: Final = ("model", "serial", "wwn", "comment", "exclude", "detail", "checks")

# The keys of one manual device, both required (FR-104).
_DEVICE_KEYS: Final = ("name", "type")

# How long one call of smartctl may take (ADR 0004, FR-202). Less than a
# second is no time to answer, and more than the limit of a whole run
# (NFR-08) could never be waited for.
DEFAULT_SMARTCTL_TIMEOUT: Final = 30.0
_TIMEOUT_RANGE: Final = (1.0, 15 * 60.0)

# Durations are written with a unit (ADR 0011).
_DURATION: Final = re.compile(r"([0-9]+)(s|m|h|d)")
_SECONDS: Final[Mapping[str, int]] = {"s": 1, "m": 60, "h": 3600, "d": 86400}

# Device names and types reach smartctl as arguments, so they are checked
# against strict patterns (ARCHITECTURE.md section 14): a name below /dev, a
# type made of the words, numbers and separators of `smartctl --device`.
DEVICE_NAME_PATTERN: Final = re.compile(r"/dev/[A-Za-z0-9._:+@/-]{1,250}")
DEVICE_TYPE_PATTERN: Final = re.compile(r"[a-z0-9]+(?:[,/+-][a-z0-9]+){0,15}")


class ConfigError(Exception):
    """A configuration file that cannot be used.

    `key` is the dotted key the problem belongs to, `line` its line in the
    file when it could be located. Both are for the caller, the message names
    them as well (FR-405).
    """

    def __init__(self, message: str, *, key: str | None = None, line: int | None = None) -> None:
        self.key = key
        self.line = line
        super().__init__(message)

    def __str__(self) -> str:
        message = super().__str__()
        return message if self.line is None else f"{message} (line {self.line})"


@dataclass(frozen=True)
class NotifySettings:
    """The `[notify]` section."""

    transport: TransportName = TransportName.AUTO


@dataclass(frozen=True)
class SmartctlSettings:
    """The `[smartctl]` section (ADR 0004)."""

    path: Path = SMARTCTL_PATH
    timeout_seconds: float = DEFAULT_SMARTCTL_TIMEOUT
    detail: Detail = Detail.EXTENDED


@dataclass(frozen=True)
class ManualDevice:
    """One `[[discovery.device]]` entry: a device the scan does not find (FR-104)."""

    name: str
    type: str


class SelectorKind(StrEnum):
    """What a selector of a drive compares (ADR 0024)."""

    MODEL = "model"
    SERIAL = "serial"
    WWN = "wwn"


_SELECTOR_KEYS: Final = tuple(kind.value for kind in SelectorKind)
_WWN_VALUE: Final = re.compile(r"(?:0[xX])?[0-9a-fA-F]{1,32}")


@dataclass(frozen=True)
class DriveSelector:
    """One selector of a drive, as exclude rules and per-drive overrides use it (ADR 0024).

    A model is a pattern in which `*` stands for any sequence of characters
    and `?` for one, and which has to match the whole name; upper and lower
    case count. A serial number is compared exactly, a WWN exactly in its
    digits, without a `0x` and without regard to their case.
    """

    kind: SelectorKind
    value: str

    def matches(self, identity: DriveIdentity) -> bool:
        """Whether this selector selects the drive with this identity."""
        if self.kind is SelectorKind.MODEL:
            return model_pattern(self.value).fullmatch(identity.model) is not None
        if self.kind is SelectorKind.SERIAL:
            return identity.serial == self.value
        wanted = self.value.lower().removeprefix("0x")
        return identity.wwn is not None and identity.wwn == wanted

    def describe(self) -> str:
        """Return the selector as it is written in the configuration."""
        return f'{self.kind.value} = "{self.value}"'


def model_pattern(pattern: str) -> re.Pattern[str]:
    """Return the regular expression of a model pattern (ADR 0024)."""
    translated = "".join(
        ".*" if character == "*" else "." if character == "?" else re.escape(character)
        for character in pattern
    )
    return re.compile(translated, re.DOTALL)


@dataclass(frozen=True)
class DiscoverySettings:
    """The `[discovery]` section (ADR 0005)."""

    devices: tuple[ManualDevice, ...] = ()
    exclude: tuple[DriveSelector, ...] = ()


@dataclass(frozen=True)
class CheckOverride:
    """One `[checks."<id>"]` or `[drive.checks."<id>"]` table (ADR 0011).

    Every value is what it overrides; `None` leaves the default in place. A
    threshold is one number, or, for the one check whose thresholds differ
    per drive class, a table that names the classes.
    """

    enabled: bool | None = None
    notice: int | Mapping[str, int] | None = None
    warning: int | Mapping[str, int] | None = None
    critical: int | Mapping[str, int] | None = None


@dataclass(frozen=True)
class DriveOverride:
    """One `[[drive]]` entry: what is overridden for one drive (FR-403).

    A drive is selected by exactly one of model, serial or WWN (ADR 0024).
    The first entry that matches a drive wins (ARCHITECTURE.md section 6).
    """

    selector: DriveSelector
    comment: str | None = None
    exclude: bool = False
    detail: Detail | None = None
    checks: Mapping[str, CheckOverride] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    """The effective configuration.

    `source` is the file the configuration was read from, or `None` when
    there is no file at all and only the built-in defaults are in effect
    (FR-401).
    """

    notify: NotifySettings = NotifySettings()
    smartctl: SmartctlSettings = field(default_factory=SmartctlSettings)
    discovery: DiscoverySettings = field(default_factory=DiscoverySettings)
    checks: Mapping[str, CheckOverride] = field(default_factory=dict)
    drives: tuple[DriveOverride, ...] = ()
    source: Path | None = None


def load_config(path: Path | None = None) -> Config:
    """Load and validate the configuration and return it.

    A missing or empty file is not an error: the built-in defaults are used
    (FR-401). An unreadable or invalid file raises `ConfigError`.

    Version 1 reads one file. A drop-in directory and a cluster-wide file are
    merged in here later, without changing the format (ADR 0011).
    """
    source = CONFIG_PATH if path is None else path
    text = _read(source)
    if text is None:
        return Config()

    data = _parse(text, source)
    _check_known_keys(data, text)
    return _build(data, source=source, text=text)


def load_effective(
    path: Path | None = None, *, last_good: Path | None = LAST_GOOD_CONFIG_PATH
) -> tuple[Config, ConfigError | None]:
    """Load the configuration the way a run does (FR-406).

    The file is tried first. When it is invalid, the last configuration that
    passed validation is used, and when there is none the built-in defaults;
    the run continues either way. The error is returned with the
    configuration, so that the caller can raise the warning that names it.
    """
    try:
        return load_config(path), None
    except ConfigError as error:
        fallback = load_last_good(last_good) if last_good is not None else None
        return (fallback if fallback is not None else Config()), error


def save_last_good(config: Config, path: Path | None = LAST_GOOD_CONFIG_PATH) -> None:
    """Save the effective configuration as the last good one (ADR 0011).

    A new directory is created only for the file of the tool itself. An
    administrator who runs a command without the rights to write the state
    directory gets the error from the command, not from the run: the caller
    decides what a failed save means.
    """
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_to_json(config), indent=2) + "\n", encoding="utf-8")


def load_last_good(path: Path | None = LAST_GOOD_CONFIG_PATH) -> Config | None:
    """Return the last configuration that passed validation, or `None`.

    `None` also answers a file that cannot be read or cannot be understood:
    the run then continues with the built-in defaults (FR-406).
    """
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _from_json(data, source=path)
    except (ConfigError, ValueError, TypeError):
        return None


def _to_json(config: Config) -> dict[str, object]:
    """Return the effective configuration as one JSON document (ADR 0011)."""
    return {
        "notify": {"transport": config.notify.transport.value},
        "smartctl": {
            "path": str(config.smartctl.path),
            "timeout_seconds": config.smartctl.timeout_seconds,
            "detail": config.smartctl.detail.value,
        },
        "discovery": {
            "devices": [
                {"name": device.name, "type": device.type} for device in config.discovery.devices
            ],
            "exclude": [
                {"kind": rule.kind.value, "value": rule.value} for rule in config.discovery.exclude
            ],
        },
        "checks": {
            name: {
                "enabled": override.enabled,
                "notice": override.notice,
                "warning": override.warning,
                "critical": override.critical,
            }
            for name, override in config.checks.items()
        },
        "drives": [
            {
                "kind": entry.selector.kind.value,
                "value": entry.selector.value,
                "comment": entry.comment,
                "exclude": entry.exclude,
                "detail": entry.detail.value if entry.detail is not None else None,
                "checks": {
                    name: {
                        "enabled": override.enabled,
                        "notice": override.notice,
                        "warning": override.warning,
                        "critical": override.critical,
                    }
                    for name, override in entry.checks.items()
                },
            }
            for entry in config.drives
        ],
    }


def _from_json(data: Mapping[str, object], *, source: Path) -> Config:
    """Return the configuration of a last-good document."""
    notify = _table_of(data.get("notify"))
    smartctl = _table_of(data.get("smartctl"))
    discovery = _table_of(data.get("discovery"))
    return Config(
        notify=NotifySettings(
            transport=TransportName(_json_text(notify, "transport") or TransportName.AUTO.value)
        ),
        smartctl=SmartctlSettings(
            path=Path(_json_text(smartctl, "path") or str(SMARTCTL_PATH)),
            timeout_seconds=_number(
                smartctl, "timeout_seconds", SmartctlSettings().timeout_seconds
            ),
            detail=Detail(_json_text(smartctl, "detail") or Detail.EXTENDED.value),
        ),
        discovery=DiscoverySettings(
            devices=tuple(
                ManualDevice(
                    name=_json_text(device, "name") or "",
                    type=_json_text(device, "type") or "",
                )
                for device in _list_of(discovery.get("devices"))
            ),
            exclude=tuple(
                DriveSelector(
                    SelectorKind(_json_text(rule, "kind") or SelectorKind.MODEL.value),
                    _json_text(rule, "value") or "",
                )
                for rule in _list_of(discovery.get("exclude"))
            ),
        ),
        checks=_overrides_of(_table_of(data.get("checks"))),
        drives=tuple(
            DriveOverride(
                selector=DriveSelector(
                    SelectorKind(_json_text(entry, "kind") or SelectorKind.MODEL.value),
                    _json_text(entry, "value") or "",
                ),
                comment=_json_text(entry, "comment"),
                exclude=bool(entry.get("exclude")),
                detail=Detail(_json_text(entry, "detail") or Detail.EXTENDED.value)
                if entry.get("detail") is not None
                else None,
                checks=_overrides_of(_table_of(entry.get("checks"))),
            )
            for entry in _list_of(data.get("drives"))
        ),
        source=source,
    )


def _overrides_of(table: Mapping[str, object]) -> dict[str, CheckOverride]:
    """Return the check overrides of a last-good document."""
    result: dict[str, CheckOverride] = {}
    for name, entry in table.items():
        override = _override_of(_table_of(entry))
        if override != CheckOverride():
            result[name] = override
    return result


def _override_of(table: Mapping[str, object]) -> CheckOverride:
    """Return one check override of a last-good document."""
    enabled = table.get("enabled")
    return CheckOverride(
        enabled=enabled if isinstance(enabled, bool) else None,
        notice=_json_number(table, "notice"),
        warning=_json_number(table, "warning"),
        critical=_json_number(table, "critical"),
    )


def _json_number(table: Mapping[str, object], key: str) -> int | Mapping[str, int] | None:
    """Return a threshold of a last-good document: one number or a table of them."""
    value = table.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        numbers = {
            name: number
            for name, number in value.items()
            if isinstance(name, str) and isinstance(number, int) and not isinstance(number, bool)
        }
        return numbers or None
    return None


def _json_text(node: Mapping[str, object], key: str) -> str | None:
    """Return a string value of a last-good document, or `None`."""
    value = node.get(key)
    return value if isinstance(value, str) else None


def _list_of(value: object) -> tuple[Mapping[str, object], ...]:
    """Return the tables of a JSON list, or an empty one."""
    if not isinstance(value, list):
        return ()
    return tuple(entry for entry in value if isinstance(entry, dict))


def _number(node: Mapping[str, object], key: str, default: float) -> float:
    """Return a number of a last-good document, or the default."""
    value = node.get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def drive_override(config: Config, identity: DriveIdentity) -> DriveOverride | None:
    """Return the first per-drive override that selects this drive, or `None`.

    The first matching entry wins (ARCHITECTURE.md section 6).
    """
    return next((entry for entry in config.drives if entry.selector.matches(identity)), None)


def effective_checks(
    config: Config, identity: DriveIdentity, drive_class: DriveClass
) -> dict[str, EffectiveCheck]:
    """Return the settings of every check as they apply to one drive.

    The built-in defaults of the catalog, overridden by the global
    configuration, overridden by the first matching per-drive override
    (ARCHITECTURE.md section 6, FR-402, FR-403).
    """
    drive = drive_override(config, identity)
    result: dict[str, EffectiveCheck] = {}
    for name, item in default_checks(drive_class).items():
        enabled = item.enabled
        thresholds = item.thresholds
        global_override = config.checks.get(name)
        drive_check = drive.checks.get(name) if drive is not None else None
        for override in (global_override, drive_check):
            if override is None:
                continue
            if override.enabled is not None:
                enabled = override.enabled
            if thresholds is not None:
                thresholds = _merged(drive_class, thresholds, override)
        result[name] = EffectiveCheck(check=item.check, enabled=enabled, thresholds=thresholds)
    return result


def effective_check(config: Config, check: Check, drive_class: DriveClass | None) -> EffectiveCheck:
    """Return the settings of one check as the global configuration leaves them.

    The per-drive overrides are left out: this answers for the configuration
    as a whole, for one drive class. `drive_class` is `None` for a check
    without thresholds.
    """
    item = (
        default_checks(drive_class)[check.id]
        if drive_class is not None
        else EffectiveCheck(check, check.enabled, check.thresholds)
    )
    override = config.checks.get(check.id)
    if override is None:
        return item
    enabled = item.enabled if override.enabled is None else override.enabled
    thresholds = item.thresholds
    if thresholds is not None and drive_class is not None:
        thresholds = _merged(drive_class, thresholds, override)
    return EffectiveCheck(check, enabled, thresholds)


def _merged(drive_class: DriveClass, current: Thresholds, override: CheckOverride) -> Thresholds:
    """Return the thresholds with one override applied to them."""
    values: dict[str, int | None] = {
        "notice": current.notice,
        "warning": current.warning,
        "critical": current.critical,
    }
    for severity, value in (
        ("notice", override.notice),
        ("warning", override.warning),
        ("critical", override.critical),
    ):
        if value is None:
            continue
        if isinstance(value, Mapping):
            # A table of the classes: the entry of this drive's class counts,
            # a class the table leaves out keeps its default.
            value = value.get(drive_class.value)
            if value is None:
                continue
        values[severity] = value
    return Thresholds(**values)


def _read(path: Path) -> str | None:
    """Return the content of the file, or `None` when it does not exist."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error.strerror}") from error
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path} is not valid UTF-8: {error}") from error


def _parse(text: str, path: Path) -> dict[str, object]:
    """Return the parsed document, or raise `ConfigError`."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error


def _check_known_keys(data: Mapping[str, object], text: str) -> None:
    """Reject every section and key this version does not know (ADR 0011)."""
    for name, value in data.items():
        if name in _DYNAMIC_SECTIONS:
            # `checks` and `drive` are validated by their own builders: the
            # keys of `checks` are the identifiers of the catalog, and
            # `drive` is a list of tables.
            if not isinstance(value, (dict, list)):
                raise ConfigError(
                    f'"{name}" must be a table or a list of tables',
                    key=name,
                    line=_find_line(text, name),
                )
            continue
        known = _SCHEMA.get(name)
        if known is None:
            if not isinstance(value, dict):
                raise ConfigError(f'unknown key "{name}"', key=name, line=_find_line(text, name))
            raise ConfigError(
                f"unknown section [{name}]", key=name, line=_find_line(text, f"[{name}]")
            )
        if not isinstance(value, dict):
            raise ConfigError(
                f"[{name}] must be a table", key=name, line=_find_line(text, f"[{name}]")
            )
        for key in value:
            if key not in known:
                raise ConfigError(
                    f'unknown key "{key}" in section [{name}]',
                    key=f"{name}.{key}",
                    line=_find_line(text, key),
                )


def _build(data: Mapping[str, object], *, source: Path, text: str) -> Config:
    """Return the configuration of a document whose keys are known."""
    return Config(
        notify=_notify(_table(data.get("notify")), text),
        smartctl=_smartctl(_table(data.get("smartctl")), text),
        discovery=_discovery(_table(data.get("discovery")), text),
        checks=_checks(_table(data.get("checks")), text),
        drives=_drives(data.get("drive"), text),
        source=source,
    )


def _checks(
    section: Mapping[str, object], text: str, *, where: str = "checks"
) -> dict[str, CheckOverride]:
    """Return the check overrides of one table, validated and without no-op entries."""
    result: dict[str, CheckOverride] = {}
    for name, table in section.items():
        check = CATALOG.get(name)
        if check is None:
            raise ConfigError(
                f'unknown check "{name}" in [{where}]',
                key=f'{where}."{name}"',
                # The check names a section of its own, so the line is looked
                # up in the form the section is written in.
                line=(
                    _find_line(text, f'[{where}."{name}"]')
                    or _find_line(text, f"[{where}.'{name}']")
                    or _find_line(text, name)
                ),
            )
        override = _check_override(_table_of(table), check, where=f'{where}."{name}"', text=text)
        if override != CheckOverride():
            result[name] = override
    return result


def _check_override(
    table: Mapping[str, object], check: Check, *, where: str, text: str
) -> CheckOverride:
    """Return one table that overrides one check, validated and normalized."""
    for key in table:
        if key not in check.slots:
            allowed = ", ".join(f'"{slot}"' for slot in sorted(check.slots))
            raise ConfigError(
                f'unknown key "{key}" in [{where}], this check accepts {allowed}',
                key=f"{where}.{key}",
                line=_find_line(text, key),
            )
    override = CheckOverride(
        enabled=_boolean(table, "enabled", f"{where}.enabled", text),
        notice=_threshold(table, "notice", check, where, text),
        warning=_threshold(table, "warning", check, where, text),
        critical=_threshold(table, "critical", check, where, text),
    )
    normalized = _normalized(override, check)
    return normalized if normalized is not None else CheckOverride()


def _normalized(override: CheckOverride, check: Check) -> CheckOverride | None:
    """Return the override without the parts that repeat the default, or `None`.

    The reference of the configuration lists every key with its default, and
    loading it must change nothing (ADR 0011).
    """
    values: dict[str, object] = {
        "enabled": override.enabled if override.enabled != check.enabled else None
    }
    for severity in ("notice", "warning", "critical"):
        value = getattr(override, severity)
        if value is None:
            values[severity] = None
        elif isinstance(value, Mapping):
            kept = {
                name: number
                for name, number in value.items()
                if number != _default_threshold(check, severity, name)
            }
            values[severity] = kept or None
        else:
            defaults = {_default_threshold(check, severity, name.value) for name in check.classes}
            values[severity] = None if defaults == {value} else value
    normalized = CheckOverride(**values)  # type: ignore[arg-type]
    return normalized if normalized != CheckOverride() else None


def _default_threshold(check: Check, severity: str, class_name: str | None) -> int | None:
    """Return the built-in default of one threshold of a check, for one class."""
    thresholds: Thresholds | None = None
    if check.per_class is not None and class_name is not None:
        thresholds = check.per_class.get(DriveClass(class_name))
    elif check.per_class is None:
        thresholds = check.thresholds
    if thresholds is None:
        return None
    value: object = getattr(thresholds, severity, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _threshold(
    table: Mapping[str, object], severity: str, check: Check, where: str, text: str
) -> int | Mapping[str, int] | None:
    """Return one threshold of a check table, validated (FR-405)."""
    value = table.get(severity)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, dict) and check.per_class is not None:
            per_class: dict[str, int] = {}
            for name, number in value.items():
                if name not in _CLASS_NAMES or DriveClass(name) not in check.classes:
                    raise ConfigError(
                        f'"{where}.{severity}" names the class "{name}", which this check'
                        " does not apply to",
                        key=f"{where}.{severity}",
                        line=_find_line(text, severity),
                    )
                if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                    raise ConfigError(
                        f'"{where}.{severity}" must hold whole numbers of 0 or more',
                        key=f"{where}.{severity}",
                        line=_find_line(text, severity),
                    )
                per_class[name] = number
            return per_class or None
        raise ConfigError(
            f'"{where}.{severity}" must be a whole number of 0 or more, found'
            f" {type(value).__name__}",
            key=f"{where}.{severity}",
            line=_find_line(text, severity),
        )
    if value < 0:
        raise ConfigError(
            f'"{where}.{severity}" must be a whole number of 0 or more, found {value}',
            key=f"{where}.{severity}",
            line=_find_line(text, severity),
        )
    return value


def _drives(entries: object, text: str) -> tuple[DriveOverride, ...]:
    """Return the per-drive overrides of `[[drive]]`, validated."""
    if entries is None:
        return ()
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ConfigError(
            '"drive" must be a list of tables, such as [[drive]]',
            key="drive",
            line=_find_line(text, "[[drive]]"),
        )
    return tuple(_drive_override(entry, number, text) for number, entry in enumerate(entries, 1))


def _drive_override(entry: Mapping[str, object], number: int, text: str) -> DriveOverride:
    """Return one `[[drive]]` entry; `number` counts the entries from 1."""
    where = f"[[drive]] number {number}"
    for key in entry:
        if key not in _DRIVE_KEYS:
            raise ConfigError(
                f'unknown key "{key}" in {where}', key=f"drive.{key}", line=_find_line(text, key)
            )
    selectors = [key for key in _SELECTOR_KEYS if key in entry]
    if len(selectors) != 1:
        names = ", ".join(f'"{key}"' for key in _SELECTOR_KEYS)
        raise ConfigError(
            f"{where} needs exactly one of {names}, found {len(selectors)}",
            key="drive",
            line=_find_line(text, "[[drive]]"),
        )
    (key,) = selectors
    value = _string(entry, key, f"drive.{key}", text)
    if not value:
        raise ConfigError(
            f'"{key}" in {where} must not be empty', key=f"drive.{key}", line=_find_line(text, key)
        )
    if key == SelectorKind.WWN.value and not _WWN_VALUE.fullmatch(value):
        raise ConfigError(
            f'"wwn" in {where} must be hexadecimal digits, found "{value}"',
            key="drive.wwn",
            line=_find_line(text, "wwn"),
        )

    raw_detail = _string(entry, "detail", "drive.detail", text)
    detail = (
        Detail(_choice(raw_detail, _DETAIL_VALUES, "drive.detail", text))
        if raw_detail is not None
        else None
    )
    return DriveOverride(
        selector=DriveSelector(SelectorKind(key), value),
        comment=_string(entry, "comment", "drive.comment", text),
        exclude=_boolean(entry, "exclude", "drive.exclude", text) is True,
        detail=detail,
        checks=_checks(_table_of(entry.get("checks")), text, where="drive.checks"),
    )


def _table_of(value: object) -> Mapping[str, object]:
    """Return a TOML table, or an empty one when the value is of another type."""
    return value if isinstance(value, dict) else {}


def _notify(section: Mapping[str, object], text: str) -> NotifySettings:
    raw_transport = _string(section, "transport", "notify.transport", text)
    if raw_transport is None:
        return NotifySettings()
    return NotifySettings(
        transport=TransportName(_choice(raw_transport, _TRANSPORT_VALUES, "notify.transport", text))
    )


def _smartctl(section: Mapping[str, object], text: str) -> SmartctlSettings:
    settings = SmartctlSettings()

    raw_path = _string(section, "path", "smartctl.path", text)
    if raw_path is not None:
        if not raw_path.startswith("/") or "\0" in raw_path:
            raise ConfigError(
                f'"smartctl.path" must be an absolute path, found "{raw_path}"',
                key="smartctl.path",
                line=_find_line(text, "path"),
            )
        settings = SmartctlSettings(path=Path(raw_path))

    raw_timeout = _string(section, "timeout", "smartctl.timeout", text)
    timeout = settings.timeout_seconds
    if raw_timeout is not None:
        timeout = _duration(raw_timeout, "smartctl.timeout", text)
        low, high = _TIMEOUT_RANGE
        if not low <= timeout <= high:
            raise ConfigError(
                f'"smartctl.timeout" must be between 1s and 15m, found "{raw_timeout}"',
                key="smartctl.timeout",
                line=_find_line(text, "timeout"),
            )

    raw_detail = _string(section, "detail", "smartctl.detail", text)
    detail = settings.detail
    if raw_detail is not None:
        detail = Detail(_choice(raw_detail, _DETAIL_VALUES, "smartctl.detail", text))

    return SmartctlSettings(path=settings.path, timeout_seconds=timeout, detail=detail)


def _discovery(section: Mapping[str, object], text: str) -> DiscoverySettings:
    devices = _tables(section, "device", text)
    rules = _tables(section, "exclude", text)
    return DiscoverySettings(
        devices=tuple(_device(entry, number, text) for number, entry in enumerate(devices, 1)),
        exclude=tuple(_selector(rule, number, text) for number, rule in enumerate(rules, 1)),
    )


def _tables(section: Mapping[str, object], key: str, text: str) -> list[Mapping[str, object]]:
    """Return a list of tables of `[discovery]`, or an empty one when it is absent."""
    entries = section.get(key)
    if entries is None:
        return []
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ConfigError(
            f'"discovery.{key}" must be a list of tables, such as [[discovery.{key}]]',
            key=f"discovery.{key}",
            line=_find_line(text, key),
        )
    return entries


def _selector(rule: Mapping[str, object], number: int, text: str) -> DriveSelector:
    """Return one exclude rule; `number` counts the rules from 1 (ADR 0024)."""
    where = f"exclude rule number {number}"
    for key in rule:
        if key not in _SELECTOR_KEYS:
            raise ConfigError(
                f'unknown key "{key}" in {where}',
                key=f"discovery.exclude.{key}",
                line=_find_line(text, "exclude"),
            )
    if len(rule) != 1:
        names = ", ".join(f'"{key}"' for key in _SELECTOR_KEYS)
        raise ConfigError(
            f"{where} needs exactly one of {names}",
            key="discovery.exclude",
            line=_find_line(text, "exclude"),
        )

    (key,) = rule
    value = _string(rule, key, f"discovery.exclude.{key}", text)
    if not value:
        raise ConfigError(
            f'"{key}" in {where} must not be empty',
            key=f"discovery.exclude.{key}",
            line=_find_line(text, "exclude"),
        )
    if key == SelectorKind.WWN.value and not _WWN_VALUE.fullmatch(value):
        raise ConfigError(
            f'"wwn" in {where} must be hexadecimal digits, found "{value}"',
            key="discovery.exclude.wwn",
            line=_find_line(text, "exclude"),
        )
    return DriveSelector(SelectorKind(key), value)


def _device(entry: Mapping[str, object], number: int, text: str) -> ManualDevice:
    """Return one manual device; `number` counts the entries from 1."""
    where = f"[[discovery.device]] number {number}"
    for key in entry:
        if key not in _DEVICE_KEYS:
            raise ConfigError(
                f'unknown key "{key}" in {where}',
                key=f"discovery.device.{key}",
                line=_find_line(text, key),
            )

    values: dict[str, str] = {}
    for key in _DEVICE_KEYS:
        value = _string(entry, key, f"discovery.device.{key}", text)
        if value is None:
            raise ConfigError(
                f'{where} needs "{key}"', key=f"discovery.device.{key}", line=_find_line(text, "[[")
            )
        values[key] = value

    name, device_type = values["name"], values["type"]
    if not DEVICE_NAME_PATTERN.fullmatch(name) or ".." in PurePosixPath(name).parts:
        raise ConfigError(
            f'"name" in {where} must be a device below /dev, found "{name}"',
            key="discovery.device.name",
            line=_find_line(text, "name"),
        )
    if not DEVICE_TYPE_PATTERN.fullmatch(device_type):
        raise ConfigError(
            f'"type" in {where} must be a device type of smartctl such as "sat" or'
            f' "megaraid,0", found "{device_type}"',
            key="discovery.device.type",
            line=_find_line(text, "type"),
        )
    return ManualDevice(name=name, type=device_type)


def _string(section: Mapping[str, object], key: str, dotted: str, text: str) -> str | None:
    """Return a string value, `None` when it is absent, or raise `ConfigError`."""
    value = section.get(key)
    if value is None or isinstance(value, str):
        return value
    raise ConfigError(
        f'"{dotted}" must be a string, found {type(value).__name__}',
        key=dotted,
        line=_find_line(text, key),
    )


def _boolean(section: Mapping[str, object], key: str, dotted: str, text: str) -> bool | None:
    """Return a boolean value, `None` when it is absent, or raise `ConfigError`."""
    value = section.get(key)
    if value is None or isinstance(value, bool):
        return value
    raise ConfigError(
        f'"{dotted}" must be true or false, found {type(value).__name__}',
        key=dotted,
        line=_find_line(text, key),
    )


def _choice(value: str, choices: tuple[str, ...], dotted: str, text: str) -> str:
    """Return a value that must be one of a few, or raise `ConfigError`."""
    if value in choices:
        return value
    names = ", ".join(f'"{choice}"' for choice in choices)
    raise ConfigError(
        f'"{dotted}" must be one of {names}, found "{value}"',
        key=dotted,
        line=_find_line(text, dotted.rsplit(".", 1)[-1]),
    )


def _duration(value: str, dotted: str, text: str) -> float:
    """Return a duration such as "30s", "5m", "6h" or "7d" in seconds (ADR 0011)."""
    match = _DURATION.fullmatch(value)
    if match is None:
        raise ConfigError(
            f'"{dotted}" must be a duration such as "30s" or "2m", found "{value}"',
            key=dotted,
            line=_find_line(text, dotted.rsplit(".", 1)[-1]),
        )
    return float(int(match.group(1)) * _SECONDS[match.group(2)])


def _table(value: object) -> Mapping[str, object]:
    """Return a TOML table, or an empty one when it is absent."""
    return value if isinstance(value, dict) else {}


def _find_line(text: str, needle: str) -> int | None:
    """Return the line a key or section starts on, as best as it can.

    Only used to point at the place of an error, so a first match by prefix is
    good enough.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith(needle):
            return number
    return None
