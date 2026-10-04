# SPDX-License-Identifier: AGPL-3.0-or-later
"""Loading and validation of the configuration file.

The file is `/etc/pve-smart-alert/config.toml`, its format and its failure
behavior are described in ADR 0011 and ARCHITECTURE.md section 8.

This module reads the part that milestone M1 needs: `[notify] transport`. The
validation is already strict — an unknown section, an unknown key, a wrong
type and an unknown value are errors that name the place (FR-405). The
remaining sections arrive with the milestone that uses them; the last-good
configuration and the run-time fallback of FR-406 belong to milestone M3 and
are deliberately not imitated here: an invalid file is an error for the
interactive commands and is reported by `pve-smart-alert doctor`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from pve_smart_alert.paths import CONFIG_PATH


class TransportName(StrEnum):
    """The values of `notify.transport` (ADR 0008, FR-506)."""

    AUTO = "auto"
    PVE_NOTIFY = "pve-notify"
    MAIL = "mail"


_TRANSPORT_VALUES: Final = tuple(item.value for item in TransportName)

# Which sections and keys this version knows. Anything else is an error
# (ADR 0011). The table grows with the sections that are implemented.
_SCHEMA: Final[Mapping[str, frozenset[str]]] = {
    "notify": frozenset({"transport"}),
}


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
class Config:
    """The effective configuration.

    `source` is the file the configuration was read from, or `None` when
    there is no file at all and only the built-in defaults are in effect
    (FR-401).
    """

    notify: NotifySettings = NotifySettings()
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
    notify = _table(data.get("notify"))
    raw_transport = notify.get("transport")
    if raw_transport is None:
        return Config(source=source)

    if not isinstance(raw_transport, str):
        raise ConfigError(
            f'"notify.transport" must be a string, found {type(raw_transport).__name__}',
            key="notify.transport",
            line=_find_line(text, "transport"),
        )
    if raw_transport not in _TRANSPORT_VALUES:
        choices = ", ".join(f'"{value}"' for value in _TRANSPORT_VALUES)
        raise ConfigError(
            f'"notify.transport" must be one of {choices}, found "{raw_transport}"',
            key="notify.transport",
            line=_find_line(text, "transport"),
        )

    return Config(notify=NotifySettings(transport=TransportName(raw_transport)), source=source)


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
