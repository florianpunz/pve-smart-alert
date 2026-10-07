# SPDX-License-Identifier: AGPL-3.0-or-later
"""Loading and validation of the configuration file.

The file is `/etc/pve-smart-alert/config.toml`, its format and its failure
behavior are described in ADR 0011 and ARCHITECTURE.md section 8.

This module reads the keys that are implemented: `[notify] transport` since
milestone M1, `[smartctl]` with `path`, `timeout` and `detail`, and the
manual devices of `[[discovery.device]]` since milestone M2. The validation
is strict: an unknown section, an unknown key, a wrong type and a value out
of range are errors that name the place (FR-405). The remaining keys arrive
with the milestone that uses them; the last-good configuration and the
run-time fallback of FR-406 belong to milestone M3 and are deliberately not
imitated here: an invalid file is an error for the interactive commands and
is reported by `pve-smart-alert doctor`.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from pve_smart_alert.paths import CONFIG_PATH, SMARTCTL_PATH


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
# (ADR 0011). The table grows with the sections that are implemented.
_SCHEMA: Final[Mapping[str, frozenset[str]]] = {
    "notify": frozenset({"transport"}),
    "smartctl": frozenset({"path", "timeout", "detail"}),
    "discovery": frozenset({"device"}),
}

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
_DEVICE_NAME: Final = re.compile(r"/dev/[A-Za-z0-9._:+@/-]{1,250}")
_DEVICE_TYPE: Final = re.compile(r"[a-z0-9]+(?:[,/+-][a-z0-9]+){0,15}")


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


@dataclass(frozen=True)
class DiscoverySettings:
    """The `[discovery]` section (ADR 0005)."""

    devices: tuple[ManualDevice, ...] = ()


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
        source=source,
    )


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
    entries = section.get("device")
    if entries is None:
        return DiscoverySettings()
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ConfigError(
            '"discovery.device" must be a list of tables, written as [[discovery.device]]',
            key="discovery.device",
            line=_find_line(text, "device"),
        )
    return DiscoverySettings(
        devices=tuple(_device(entry, number, text) for number, entry in enumerate(entries, 1))
    )


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
    if not _DEVICE_NAME.fullmatch(name) or ".." in PurePosixPath(name).parts:
        raise ConfigError(
            f'"name" in {where} must be a device below /dev, found "{name}"',
            key="discovery.device.name",
            line=_find_line(text, "name"),
        )
    if not _DEVICE_TYPE.fullmatch(device_type):
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
