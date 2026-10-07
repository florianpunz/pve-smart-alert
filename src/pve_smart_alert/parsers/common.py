# SPDX-License-Identifier: AGPL-3.0-or-later
"""What every protocol writes alike into the JSON of smartctl.

The helpers return `None` for a key that is missing or has the wrong type:
a value the drive does not report is not applicable, never guessed (FR-206).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pve_smart_alert.model import DriveIdentity


class ParseError(Exception):
    """A drive output that cannot become a snapshot."""


def section(document: Mapping[str, object], *keys: str) -> Mapping[str, object]:
    """Return a nested object, or an empty one when a part of the path is missing."""
    node: object = document
    for key in keys:
        node = node.get(key) if isinstance(node, Mapping) else None
    return node if isinstance(node, Mapping) else {}


def entries(document: Mapping[str, object], *keys: str) -> Sequence[Mapping[str, object]]:
    """Return a nested list of objects, or an empty one."""
    *path, last = keys
    node = section(document, *path).get(last)
    if not isinstance(node, list):
        return ()
    return [entry for entry in node if isinstance(entry, Mapping)]


def integer(node: Mapping[str, object], key: str) -> int | None:
    """Return an integer value; a boolean is not one."""
    value = node.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def flag(node: Mapping[str, object], key: str) -> bool | None:
    value = node.get(key)
    return value if isinstance(value, bool) else None


def text(node: Mapping[str, object], key: str) -> str | None:
    value = node.get(key)
    return value if isinstance(value, str) else None


def protocol_of(document: Mapping[str, object]) -> str | None:
    return text(section(document, "device"), "protocol")


def identity_of(document: Mapping[str, object], *, wwn: str | None = None) -> DriveIdentity:
    """Return the identity of a drive output (ADR 0005).

    Raises `ParseError` without a model name, which smartctl writes for every
    drive that answered its identify command.
    """
    model = text(document, "model_name")
    if not model or not model.strip():
        raise ParseError("smartctl reported no model name")
    return DriveIdentity.of(model, serial=text(document, "serial_number"), wwn=wwn)


def capacity_of(document: Mapping[str, object]) -> int | None:
    return integer(section(document, "user_capacity"), "bytes")


def put(metrics: dict[str, int], name: str, value: int | None) -> None:
    """Add a metric that the drive reported; leave out one it did not."""
    if value is not None:
        metrics[name] = value
