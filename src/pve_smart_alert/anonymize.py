# SPDX-License-Identifier: AGPL-3.0-or-later
"""Anonymization of recordings (ADR 0023).

One `Anonymizer` handles one archive: the device scan and the drive outputs
of one host. Every identifying value gets a placeholder from a counter of its
kind, numbered in the order the values are learned, which is the order of the
scan, and the same real value gets the same placeholder in every file:

- serial number: `ANON-SN-0001`;
- WWN: `naa` and `oui` stay, `id` becomes the counter;
- EUI-64: `oui` stays, `ext_id` becomes the counter.

Where a WWN or an EUI-64 is written as 16 hexadecimal digits in a text, the
digits of its placeholder replace it. The anonymizer fails closed: `check`
raises when any real value is left in a document, in any of its forms, and
nothing may be written then.

`pve-smart-alert dump-fixture` (FR-604) and `scripts/make_fixtures.py` use
this module; fixtures are never anonymized by hand.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator, Mapping, Sized
from dataclasses import dataclass
from typing import Final

# The placeholder of a serial number. Its four digits limit an archive to
# 9999 values of one kind, far more than any host has.
SERIAL_PLACEHOLDER: Final = "ANON-SN-{:04d}"
SERIAL_PLACEHOLDER_PATTERN: Final = re.compile(r"ANON-SN-\d{4}")
COUNTER_LIMIT: Final = 9999

# A real value shorter than this is replaced only in its own field: in a
# text it could stand for something else, and it carries no identity anyway
# (ADR 0023).
MIN_SEARCHED_LENGTH: Final = 4


class AnonymizationError(Exception):
    """A recording that cannot be anonymized safely.

    The message never contains the real value it is about.
    """


@dataclass(frozen=True)
class Wwn:
    """A World Wide Name as smartctl writes it: authority, vendor, number."""

    naa: int
    oui: int
    id: int

    @property
    def hex(self) -> str:
        """The 16 hexadecimal digits that `lsblk` and udev write."""
        return f"{(self.naa << 60) | (self.oui << 36) | self.id:016x}"


@dataclass(frozen=True)
class Eui64:
    """An EUI-64 of an NVMe namespace as smartctl writes it: vendor, number."""

    oui: int
    ext_id: int

    @property
    def hex(self) -> str:
        """The 16 hexadecimal digits that `lsblk` and udev write."""
        return f"{(self.oui << 40) | self.ext_id:016x}"


class Anonymizer:
    """Replaces the identifying values of one archive with placeholders."""

    def __init__(self) -> None:
        self._serials: dict[str, str] = {}
        self._wwns: dict[Wwn, Wwn] = {}
        self._euis: dict[Eui64, Eui64] = {}

    def learn(self, drive: Mapping[str, object]) -> None:
        """Number the identifiers of one drive output that are new.

        Call it for the drives in the order of the scan before anything is
        anonymized, so that the numbers follow the scan (ADR 0023).
        """
        serial = drive.get("serial_number")
        if isinstance(serial, str) and serial and serial not in self._serials:
            self._serials[serial] = SERIAL_PLACEHOLDER.format(_next(self._serials))
        wwn = _wwn(drive.get("wwn"))
        if wwn is not None and wwn not in self._wwns:
            self._wwns[wwn] = Wwn(wwn.naa, wwn.oui, _next(self._wwns))
        for eui in _euis(drive):
            if eui not in self._euis:
                self._euis[eui] = Eui64(eui.oui, _next(self._euis))

    def drive(self, drive: Mapping[str, object]) -> dict[str, object]:
        """Return an anonymized copy of one drive output of smartctl."""
        self.learn(drive)
        result = copy.deepcopy(dict(drive))

        serial = result.get("serial_number")
        if isinstance(serial, str) and serial in self._serials:
            result["serial_number"] = self._serials[serial]
        wwn = _wwn(result.get("wwn"))
        if wwn is not None:
            result["wwn"] = _wwn_object(self._wwns[wwn])
        for namespace in _namespaces(result):
            eui = _eui(namespace.get("eui64"))
            if eui is not None:
                namespace["eui64"] = _eui_object(self._euis[eui])

        replaced = self._replace_text(result)
        assert isinstance(replaced, dict)
        return replaced

    def document(self, document: object) -> object:
        """Return a copy of any other document, with the known values replaced in its texts."""
        return self._replace_text(copy.deepcopy(document))

    def check(self, document: object, *, name: str) -> None:
        """Raise `AnonymizationError` when a real value is left in a document.

        Searched are the texts for every learned value in each of its forms,
        and the fields that hold identifiers for anything but a placeholder.
        `name` names the document in the message.
        """
        text = json.dumps(document, ensure_ascii=False).lower()
        found = [
            kind
            for kind, value in self._searched_forms()
            if len(value) >= MIN_SEARCHED_LENGTH and value.lower() in text
        ]
        found.extend(self._unreplaced_fields(document))
        if found:
            kinds = ", ".join(dict.fromkeys(found))
            raise AnonymizationError(f"{name} still contains a real value: {kinds}")

    def _searched_forms(self) -> Iterator[tuple[str, str]]:
        """Return every learned real value, in every form it is written in."""
        for serial in self._serials:
            yield "serial number", serial
        for wwn in self._wwns:
            yield "WWN", wwn.hex
        for eui in self._euis:
            yield "EUI-64", eui.hex

    def _unreplaced_fields(self, document: object) -> Iterator[str]:
        """Return the kinds of identifier fields that do not hold a placeholder."""
        anonymized_wwns = set(self._wwns.values())
        anonymized_euis = set(self._euis.values())
        for key, value in _fields(document):
            if key == "serial_number" and not (
                isinstance(value, str) and SERIAL_PLACEHOLDER_PATTERN.fullmatch(value)
            ):
                yield "serial number"
            elif key == "wwn" and isinstance(value, dict):
                if _wwn(value) not in anonymized_wwns:
                    yield "WWN"
            elif key == "eui64" and isinstance(value, dict) and _eui(value) not in anonymized_euis:
                yield "EUI-64"

    def _replace_text(self, node: object) -> object:
        """Replace the learned values in every text of a document."""
        if isinstance(node, str):
            return self._replace_in(node)
        if isinstance(node, list):
            return [self._replace_text(item) for item in node]
        if isinstance(node, dict):
            return {key: self._replace_text(value) for key, value in node.items()}
        return node

    def _replace_in(self, text: str) -> str:
        for serial, placeholder in self._serials.items():
            if len(serial) >= MIN_SEARCHED_LENGTH:
                text = text.replace(serial, placeholder)
        pairs = [(real.hex, anonymized.hex) for real, anonymized in self._wwns.items()]
        pairs += [(real.hex, anonymized.hex) for real, anonymized in self._euis.items()]
        for real_hex, anonymized_hex in pairs:
            text = re.sub(re.escape(real_hex), anonymized_hex, text, flags=re.IGNORECASE)
        return text


def _next(numbered: Sized) -> int:
    """Return the next number of a counter, within the four digits of a placeholder."""
    number = len(numbered) + 1
    if number > COUNTER_LIMIT:
        raise AnonymizationError(f"more than {COUNTER_LIMIT} values of one kind")
    return number


def _wwn(value: object) -> Wwn | None:
    """Return the WWN of a `wwn` object of smartctl, or `None`."""
    if not isinstance(value, dict):
        return None
    naa, oui, number = value.get("naa"), value.get("oui"), value.get("id")
    if isinstance(naa, int) and isinstance(oui, int) and isinstance(number, int):
        return Wwn(naa, oui, number)
    return None


def _eui(value: object) -> Eui64 | None:
    """Return the EUI-64 of an `eui64` object of smartctl, or `None`."""
    if not isinstance(value, dict):
        return None
    oui, ext_id = value.get("oui"), value.get("ext_id")
    if isinstance(oui, int) and isinstance(ext_id, int):
        return Eui64(oui, ext_id)
    return None


def _wwn_object(wwn: Wwn) -> dict[str, object]:
    return {"naa": wwn.naa, "oui": wwn.oui, "id": wwn.id}


def _eui_object(eui: Eui64) -> dict[str, object]:
    return {"oui": eui.oui, "ext_id": eui.ext_id}


def _namespaces(drive: Mapping[str, object]) -> Iterator[dict[str, object]]:
    """Return the NVMe namespaces of a drive output."""
    namespaces = drive.get("nvme_namespaces")
    if isinstance(namespaces, list):
        yield from (namespace for namespace in namespaces if isinstance(namespace, dict))


def _euis(drive: Mapping[str, object]) -> Iterator[Eui64]:
    for namespace in _namespaces(drive):
        eui = _eui(namespace.get("eui64"))
        if eui is not None:
            yield eui


def _fields(node: object) -> Iterator[tuple[str, object]]:
    """Return every key of a document with its value, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _fields(value)
    elif isinstance(node, list):
        for item in node:
            yield from _fields(item)
