# SPDX-License-Identifier: AGPL-3.0-or-later
"""Anonymization of recordings (ADR 0023).

One `Anonymizer` handles one archive: the device scan and the drive outputs
of one host. Every identifying value gets a placeholder from a counter of its
kind, numbered in the order the values are learned, which is the order of the
scan, and the same real value gets the same placeholder in every file:

- serial number: `ANON-SN-0001`;
- WWN: `naa` and `oui` stay, `id` becomes the counter;
- EUI-64: `oui` stays, `ext_id` becomes the counter;
- the logical unit id and the SAS addresses of a SCSI drive, which smartctl
  writes as `0x` and hexadecimal digits: an NAA 5 name is a WWN and shares
  its counter, an NAA 6 name keeps its authority and vendor, and any other
  name becomes a counter in its own number of digits (ADR 0026).

Where a WWN or an EUI-64 is written as 16 hexadecimal digits in a text, the
digits of its placeholder replace it. In the output of `lsblk`, drives that
the scan does not list continue the counters, and a UUID becomes the counter
in its own notation, `00000000-0000-0000-0000-000000000001`. An NGUID, which
lsblk writes as `eui.` and 32 hexadecimal digits, is the vendor-specific
extension in its first half and the EUI-64 of the namespace in its second
(Research 06): the first half becomes a counter of its own, the EUI-64 its
placeholder. The anonymizer fails closed: `check`
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

# The fields of `lsblk` that hold the UUID of a file system, a partition or
# a partition table. They identify an installation (ADR 0023).
UUID_KEYS: Final = ("uuid", "partuuid", "ptuuid")

# How lsblk writes the WWN of an ATA or SCSI drive and the EUI-64 of an NVMe
# namespace (Research 06).
_LSBLK_WWN: Final = re.compile(r"0x([0-9a-f]{16})", re.IGNORECASE)
_LSBLK_EUI: Final = re.compile(r"eui\.([0-9a-f]{16})", re.IGNORECASE)
_LSBLK_NGUID: Final = re.compile(r"eui\.([0-9a-f]{16})([0-9a-f]{16})", re.IGNORECASE)

# The fields in which smartctl writes an NAA name of a SCSI drive as text:
# the logical unit id from the device identification page, and the address
# of each SAS port and of what it is attached to (ADR 0026).
NAA_TEXT_KEYS: Final = ("logical_unit_id", "sas_address", "attached_sas_address")
_NAA_TEXT: Final = re.compile(r"0x([0-9a-f]+)", re.IGNORECASE)
# An NAA 6 name has 32 digits; its first 7 are the authority and the vendor.
_NAA6_VENDOR_DIGITS: Final = 7

# A real value shorter than this is replaced only in its own field: in a
# text it could stand for something else, and it carries no identity anyway
# (ADR 0023).
MIN_SEARCHED_LENGTH: Final = 4

# A device the scan names by its node. Only these shapes name no drive: every
# other name, such as a /dev/disk/by-id link, a mapper name (which is the
# WWID when user_friendly_names is off) or a serial link, can hold an
# identifier and is replaced like the value it holds (ADR 0023, ADR 0039).
_NODE_DEVICE: Final = re.compile(
    r"/dev/(?:"
    r"sd[a-z]+[0-9]*"
    r"|nvme[0-9]+(?:n[0-9]+(?:p[0-9]+)?)?"
    r"|sg[0-9]+"
    r"|bsg/[a-z]+[0-9]+"
    r"|bus/[0-9]+"
    r"|dm-[0-9]+"
    r"|cciss/c[0-9]+d[0-9]+"
    r"|md[0-9]+"
    r"|tw[a-z]+[0-9]+"
    r")"
)
DEVICE_PLACEHOLDER: Final = "/dev/anon{}"


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
        # The form in which udev writes a serial number with underscores,
        # kept apart from the real serial numbers so that it cannot take the
        # place of another one.
        self._udev_serials: dict[str, str] = {}
        self._wwns: dict[Wwn, Wwn] = {}
        self._euis: dict[Eui64, Eui64] = {}
        self._uuids: dict[str, str] = {}
        # An NGUID by its 32 lowercase digits, with the digits of its placeholder.
        self._nguids: dict[str, str] = {}
        # An NAA name that is not a WWN, by its lowercase digits, with the
        # digits of its placeholder (ADR 0026).
        self._names: dict[str, str] = {}
        # A device name that is not a kernel name, by its name, with the
        # placeholder name of this archive.
        self._devices: dict[str, str] = {}

    def learn_device(self, name: str) -> str:
        """Return the name to record a device under (ADR 0023).

        A node such as `/dev/sda`, `/dev/nvme0n1` or `/dev/bus/6` is kept: it
        names no drive. Every other name, such as a `by-id` link or a mapper
        name, can hold the serial number or the WWID of the drive, so it is
        replaced by a placeholder of this archive, in the file name, the
        metadata and every text of the recording alike.
        """
        if _NODE_DEVICE.fullmatch(name):
            return name
        if name not in self._devices:
            self._devices[name] = DEVICE_PLACEHOLDER.format(len(self._devices) + 1)
        return self._devices[name]

    def learn(self, drive: Mapping[str, object]) -> None:
        """Number the identifiers of one drive output that are new.

        Call it for the drives in the order of the scan before anything is
        anonymized, so that the numbers follow the scan (ADR 0023).
        """
        serial = drive.get("serial_number")
        if isinstance(serial, str) and serial:
            self._learn_serial(serial)
        wwn = _wwn(drive.get("wwn"))
        if wwn is not None and wwn not in self._wwns:
            self._wwns[wwn] = Wwn(wwn.naa, wwn.oui, _next(self._wwns))
        for eui in _euis(drive):
            if eui not in self._euis:
                self._euis[eui] = Eui64(eui.oui, _next(self._euis))
        for key, value in _fields(drive):
            if key in NAA_TEXT_KEYS and isinstance(value, str):
                self._learn_naa_text(key, value)

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
        for node in _dicts(result):
            for key in NAA_TEXT_KEYS:
                value = node.get(key)
                if isinstance(value, str):
                    node[key] = self._naa_placeholder(value)

        replaced = self._replace_text(result)
        assert isinstance(replaced, dict)
        return replaced

    def document(self, document: object) -> object:
        """Return a copy of any other document, with the known values replaced in its texts."""
        return self._replace_text(copy.deepcopy(document))

    def learn_lsblk(self, document: object) -> None:
        """Number the identifiers that only the output of `lsblk` shows.

        Call it after the drives of the scan: a drive the scan does not list,
        such as the USB drive of a KVM-over-IP device, continues the counters,
        and so do the UUIDs (ADR 0023).
        """
        for node in _nodes(document):
            serial = node.get("serial")
            if isinstance(serial, str) and serial.strip():
                self._learn_serial(serial.strip())
            wwn = node.get("wwn")
            if isinstance(wwn, str):
                self._learn_lsblk_wwn(wwn)
            for key in UUID_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value and value not in self._uuids:
                    self._uuids[value] = _counter_like(value, _next(self._uuids))

    def lsblk(self, document: object) -> object:
        """Return an anonymized copy of the output of `lsblk --json`."""
        self.learn_lsblk(document)
        result = copy.deepcopy(document)
        for node in _nodes(result):
            serial = node.get("serial")
            if isinstance(serial, str) and serial.strip() in self._serials:
                node["serial"] = self._serials[serial.strip()]
            for key in UUID_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value in self._uuids:
                    node[key] = self._uuids[value]
        return self._replace_text(result)

    def _learn_lsblk_wwn(self, text: str) -> None:
        wwn = _LSBLK_WWN.fullmatch(text)
        if wwn is not None:
            self._learn_wwn(wwn.group(1))
        eui = _LSBLK_EUI.fullmatch(text)
        if eui is not None:
            self._learn_eui(eui.group(1))
        nguid = _LSBLK_NGUID.fullmatch(text)
        if nguid is not None:
            digits = (nguid.group(1) + nguid.group(2)).lower()
            anonymized_eui = self._learn_eui(nguid.group(2))
            if digits not in self._nguids:
                self._nguids[digits] = f"{_next(self._nguids):016x}{anonymized_eui.hex}"

    def _learn_serial(self, serial: str) -> str:
        """Number a serial number, if it is new, and return its placeholder.

        udev writes a space of a serial number as an underscore in the
        `by-id` link and in the `id` and `id-link` of lsblk, so that form is
        numbered with the same placeholder (ADR 0023).
        """
        if serial not in self._serials:
            placeholder = SERIAL_PLACEHOLDER.format(_next(set(self._serials.values())))
            self._serials[serial] = placeholder
            udev_form = serial.replace(" ", "_")
            if udev_form != serial and udev_form not in self._serials:
                self._udev_serials[udev_form] = placeholder
        return self._serials[serial]

    def _learn_wwn(self, digits: str) -> Wwn:
        """Number a WWN written as 16 digits, if it is new, and return its placeholder."""
        real = _wwn_of(digits)
        if real not in self._wwns:
            self._wwns[real] = Wwn(real.naa, real.oui, _next(self._wwns))
        return self._wwns[real]

    def _learn_naa_text(self, key: str, text: str) -> None:
        """Number an NAA name that smartctl writes as text, if it is new (ADR 0026).

        Raises `AnonymizationError` for a form the anonymizer does not know,
        so that it fails closed instead of keeping a real value.
        """
        match = _NAA_TEXT.fullmatch(text)
        if match is None:
            raise AnonymizationError(f"a {key} in an unknown form")
        digits = match.group(1).lower()
        if int(digits, 16) == 0 or digits in self._names:
            # A zero address, such as that of a phy attached to nothing,
            # names nothing.
            return
        if _is_wwn_digits(digits):
            self._learn_wwn(digits)
        elif len(digits) == 32 and digits[0] == "6":
            number = _next(self._names)
            vendor = digits[:_NAA6_VENDOR_DIGITS]
            self._names[digits] = f"{vendor}{number:0{32 - _NAA6_VENDOR_DIGITS}x}"
        else:
            number = _next(self._names)
            if len(f"{number:x}") > len(digits):
                raise AnonymizationError(f"a {key} too short for its placeholder")
            self._names[digits] = f"{number:0{len(digits)}x}"

    def _naa_placeholder(self, text: str) -> str:
        """Return the placeholder of an NAA name written as text, learned before."""
        match = _NAA_TEXT.fullmatch(text)
        if match is None:
            raise AnonymizationError("an NAA name in an unknown form")
        digits = match.group(1).lower()
        if int(digits, 16) == 0:
            return text
        if _is_wwn_digits(digits):
            return f"0x{self._wwns[_wwn_of(digits)].hex}"
        return f"0x{self._names[digits]}"

    def _learn_eui(self, digits: str) -> Eui64:
        """Number an EUI-64 written as 16 digits, if it is new, and return its placeholder."""
        value = int(digits, 16)
        real = Eui64(value >> 40, value & (2**40 - 1))
        if real not in self._euis:
            self._euis[real] = Eui64(real.oui, _next(self._euis))
        return self._euis[real]

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

    def check_name(self, name: str) -> None:
        """Raise when a file name of an archive still holds a real value.

        The message names no value and no file: the file name itself can be
        the value that is left (ADR 0023).
        """
        found = [
            kind
            for kind, value in self._searched_forms()
            if len(value) >= MIN_SEARCHED_LENGTH and value.lower() in name.lower()
        ]
        if found:
            kinds = ", ".join(dict.fromkeys(found))
            raise AnonymizationError(f"a file name still contains a real value: {kinds}")

    def _searched_forms(self) -> Iterator[tuple[str, str]]:
        """Return every learned real value, in every form it is written in."""
        for serial in self._serials:
            yield "serial number", serial
        for serial in self._udev_serials:
            yield "serial number", serial
        for wwn in self._wwns:
            yield "WWN", wwn.hex
        for eui in self._euis:
            yield "EUI-64", eui.hex
        for uuid in self._uuids:
            yield "UUID", uuid
        for nguid in self._nguids:
            yield "NGUID", nguid
        for name in self._names:
            yield "NAA name", name

    def _unreplaced_fields(self, document: object) -> Iterator[str]:
        """Return the kinds of identifier fields that do not hold a placeholder."""
        for key, value in _fields(document):
            kind = self._unreplaced(key, value)
            if kind is not None:
                yield kind

    def _unreplaced(self, key: str, value: object) -> str | None:
        """Return the kind of one identifier field without a placeholder, or `None`."""
        if key in ("serial_number", "serial") and value is not None:
            placeholder = isinstance(value, str) and SERIAL_PLACEHOLDER_PATTERN.fullmatch(value)
            return None if placeholder else "serial number"
        if key == "wwn" and isinstance(value, dict):
            return None if _wwn(value) in set(self._wwns.values()) else "WWN"
        if key == "wwn" and isinstance(value, str):
            # Also a WWN in a form the anonymizer does not know.
            return None if value in self._anonymized_wwn_texts() else "WWN"
        if key == "eui64" and isinstance(value, dict):
            return None if _eui(value) in set(self._euis.values()) else "EUI-64"
        if key in NAA_TEXT_KEYS and isinstance(value, str):
            if _is_zero_name(value) or value.lower() in self._anonymized_naa_texts():
                return None
            return "NAA name"
        return None

    def _anonymized_naa_texts(self) -> set[str]:
        """Return the forms in which smartctl writes the placeholders of NAA names."""
        texts = {f"0x{wwn.hex}" for wwn in self._wwns.values()}
        texts |= {f"0x{digits}" for digits in self._names.values()}
        return texts

    def _anonymized_wwn_texts(self) -> set[str]:
        """Return the forms in which lsblk writes the placeholders of WWNs and EUI-64s."""
        texts = {f"0x{wwn.hex}" for wwn in self._wwns.values()}
        texts |= {f"eui.{eui.hex}" for eui in self._euis.values()}
        texts |= {f"eui.{digits}" for digits in self._nguids.values()}
        return texts

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
        # The longest values first, so that one that contains another is
        # replaced as a whole.
        values = [
            *self._devices.items(),
            *self._serials.items(),
            *self._udev_serials.items(),
            *self._uuids.items(),
        ]
        for real, placeholder in sorted(values, key=lambda pair: -len(pair[0])):
            if len(real) >= MIN_SEARCHED_LENGTH:
                text = text.replace(real, placeholder)
        # An NGUID before the EUI-64 inside it.
        pairs = list(self._nguids.items())
        pairs += [
            (real, placeholder)
            for real, placeholder in self._names.items()
            if len(real) >= MIN_SEARCHED_LENGTH
        ]
        pairs += [(real.hex, anonymized.hex) for real, anonymized in self._wwns.items()]
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


def _is_zero_name(text: str) -> bool:
    """Whether an NAA name written as text is zero, which names nothing (ADR 0026)."""
    match = _NAA_TEXT.fullmatch(text)
    return match is not None and int(match.group(1), 16) == 0


def _is_wwn_digits(digits: str) -> bool:
    """Whether an NAA name of 16 digits is a WWN: authority 5, IEEE registered."""
    return len(digits) == 16 and digits[0] == "5"


def _wwn_of(digits: str) -> Wwn:
    """Return the WWN written as 16 hexadecimal digits."""
    value = int(digits, 16)
    return Wwn(value >> 60, (value >> 36) & 0xFFFFFF, value & (2**36 - 1))


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


def _nodes(document: object) -> Iterator[dict[str, object]]:
    """Return every device of the output of `lsblk --json`, children included."""
    stack = list(document.get("blockdevices", [])) if isinstance(document, dict) else []
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            yield node
            children = node.get("children")
            if isinstance(children, list):
                stack.extend(children)


def _counter_like(value: str, number: int) -> str:
    """Return a counter in the notation of a value: its separators kept, the rest digits.

    "4f8c2c1e-0b3a-4b6e-9d2f-1c0a5e7b9d31" becomes
    "00000000-0000-0000-0000-000000000001" for the counter 1.
    """
    positions = [index for index, character in enumerate(value) if character.isalnum()]
    digits = str(number)
    if len(positions) < len(digits):
        raise AnonymizationError("a UUID too short for its placeholder")
    characters = ["0" if character.isalnum() else character for character in value]
    for position, digit in zip(positions[-len(digits) :], digits, strict=True):
        characters[position] = digit
    return "".join(characters)


def _dicts(node: object) -> Iterator[dict[str, object]]:
    """Return every object of a document, at any depth, the document included."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _dicts(item)


def _fields(node: object) -> Iterator[tuple[str, object]]:
    """Return every key of a document with its value, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _fields(value)
    elif isinstance(node, list):
        for item in node:
            yield from _fields(item)
