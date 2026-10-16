# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every fixture is anonymized and has a recorded source (ADR 0016, ADR 0023).

This is the guard that keeps real serial numbers and WWNs out of the
repository (NFR-14): every JSON file below `tests/fixtures` is read, and every
field known to hold an identifier must hold a placeholder. A test that cannot
know the real values can still know the form of the placeholders.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

FIXTURES: Final = Path(__file__).resolve().parent.parent / "fixtures"
SOURCES: Final = FIXTURES / "SOURCES.md"

SERIAL_PLACEHOLDER: Final = re.compile(r"ANON-SN-\d{4}")
# A placeholder counter has four digits (ADR 0023).
COUNTER_LIMIT: Final = 9999
# The forms in which lsblk and the web interface write a WWN or an EUI-64.
WWN_TEXT: Final = re.compile(r"(?:0x)?([0-9a-f]{16})", re.IGNORECASE)
EUI_TEXT: Final = re.compile(r"eui\.([0-9a-f]{16})", re.IGNORECASE)
NGUID_TEXT: Final = re.compile(r"eui\.([0-9a-f]{16})([0-9a-f]{16})", re.IGNORECASE)
# The fields of lsblk that hold a UUID of a file system, partition or table.
UUID_KEYS: Final = ("uuid", "partuuid", "ptuuid")
# The fields in which smartctl writes an NAA name of a SCSI drive (ADR 0026).
NAA_TEXT_KEYS: Final = ("logical_unit_id", "sas_address", "attached_sas_address")
NAA_TEXT: Final = re.compile(r"0x([0-9a-f]+)")
REPOSITORY: Final = FIXTURES.parent.parent
# The name part of the license text kept for each license of an import.
LICENSE_TEXTS: Final = {
    "Apache-2.0": "Apache-2.0",
    "LGPL-2.1-or-later": "LGPL-2.1",
    "MIT": "MIT",
}


def fixture_files() -> list[Path]:
    return sorted(FIXTURES.rglob("*.json"))


def identifier_problems(node: object, path: str = "") -> Iterator[str]:
    """Return every field that holds an identifier that is not a placeholder."""
    if isinstance(node, list):
        for item in node:
            yield from identifier_problems(item, path + "[]")
        return
    if not isinstance(node, dict):
        return

    for key, value in node.items():
        where = f"{path}.{key}" if path else key
        if _holds_a_real_identifier(key, value):
            yield where
        else:
            yield from identifier_problems(value, where)


def _holds_a_real_identifier(key: str, value: object) -> bool:
    """Whether one field is an identifier field without a placeholder."""
    if value is None:
        return False
    if key in ("serial_number", "serial"):
        return not (isinstance(value, str) and SERIAL_PLACEHOLDER.fullmatch(value))
    if key == "wwn":
        return not _placeholder_wwn(value)
    if key == "eui64":
        return not (isinstance(value, dict) and _small(value.get("ext_id")))
    if key in UUID_KEYS:
        return not _placeholder_uuid(value)
    if key in NAA_TEXT_KEYS:
        return not _placeholder_naa(value)
    return False


def _placeholder_naa(value: object) -> bool:
    """Whether an NAA name has a counter as its number (ADR 0026).

    An NAA 5 name is a WWN, an NAA 6 name keeps its first 7 digits, and any
    other name is a counter in all its digits. Zero names nothing.
    """
    match = NAA_TEXT.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return False
    digits = match.group(1)
    if len(digits) == 16 and digits[0] == "5":
        return int(digits, 16) & (2**36 - 1) <= COUNTER_LIMIT
    if len(digits) == 32 and digits[0] == "6":
        return int(digits[7:], 16) <= COUNTER_LIMIT
    return int(digits, 16) <= COUNTER_LIMIT


def _placeholder_uuid(value: object) -> bool:
    """Whether a UUID is a counter in its notation: zeros, separators, the number."""
    if not isinstance(value, str) or not set(value) <= set("0123456789-"):
        return False
    digits = value.replace("-", "")
    return digits != "" and int(digits) <= COUNTER_LIMIT


def _placeholder_wwn(value: object) -> bool:
    """Whether a WWN, as an object of smartctl or as text, has a counter as its number."""
    if isinstance(value, dict):
        return _small(value.get("id"))
    if not isinstance(value, str):
        return False
    nguid = NGUID_TEXT.fullmatch(value)
    if nguid is not None:
        # The vendor-specific half is a counter, the other half an EUI-64.
        return (
            int(nguid.group(1), 16) <= COUNTER_LIMIT
            and int(nguid.group(2), 16) & (2**40 - 1) <= COUNTER_LIMIT
        )
    eui = EUI_TEXT.fullmatch(value)
    if eui is not None:
        return int(eui.group(1), 16) & (2**40 - 1) <= COUNTER_LIMIT
    wwn = WWN_TEXT.fullmatch(value)
    return wwn is not None and int(wwn.group(1), 16) & (2**36 - 1) <= COUNTER_LIMIT


def _small(value: object) -> bool:
    return isinstance(value, int) and 0 < value <= COUNTER_LIMIT


@pytest.mark.parametrize("path", fixture_files(), ids=lambda path: str(path.relative_to(FIXTURES)))
def test_no_fixture_holds_a_real_identifier(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))

    assert list(identifier_problems(document)) == []


def test_there_are_fixtures_to_check() -> None:
    # A guard that reads nothing guards nothing.
    assert len(fixture_files()) >= 10


@pytest.mark.parametrize(
    "document",
    [
        {"serial_number": "S2R5NX0H123456A"},
        {"wwn": {"naa": 5, "oui": 9528, "id": 61322490563}},
        {"nvme_namespaces": [{"eui64": {"oui": 9528, "ext_id": 393006802559}}]},
        {"blockdevices": [{"serial": "S2R5NX0H123456A"}]},
        {"blockdevices": [{"wwn": "0x5002538e40a1b2c3"}]},
        {"blockdevices": [{"wwn": "eui.0025385b71b02a7f"}]},
        {"blockdevices": [{"wwn": "naa.5002538e40a1b2c3"}]},
        {"blockdevices": [{"wwn": "eui.e8238fa6bf530001001b448b4a1b2c3d"}]},
        {"blockdevices": [{"uuid": "4f8c2c1e-0b3a-4b6e-9d2f-1c0a5e7b9d31"}]},
        {"blockdevices": [{"ptuuid": "abcd1234"}]},
        {"logical_unit_id": "0x5000cca04eb1c2d4"},
        {"logical_unit_id": "0x600508b1001c4d3e2f1a0b9c8d7e6f50"},
        {"logical_unit_id": "0x1234567890abcdef"},
        {"logical_unit_id": "naa.5000cca000000001"},
        {"scsi_sas_port_0": {"phy_0": {"attached_sas_address": "0x500605b00c1d2e30"}}},
    ],
)
def test_the_guard_finds_real_identifiers(document: object) -> None:
    assert list(identifier_problems(document)) != []


@pytest.mark.parametrize(
    "document",
    [
        {"serial_number": "ANON-SN-0001"},
        {"wwn": {"naa": 5, "oui": 9528, "id": 1}},
        {"nvme_namespaces": [{"eui64": {"oui": 9528, "ext_id": 2}}]},
        {"blockdevices": [{"serial": "ANON-SN-0003", "wwn": "0x5002538000000001"}]},
        {"blockdevices": [{"serial": None, "wwn": "eui.0025380000000001"}]},
        {"blockdevices": [{"wwn": "eui.0000000000000001001b440000000001"}]},
        {"blockdevices": [{"uuid": "00000000-0000-0000-0000-000000000001", "ptuuid": None}]},
        {"blockdevices": [{"partuuid": "00000001-23"}]},
        {"logical_unit_id": "0x5000cca000000001"},
        {"logical_unit_id": "0x600508b0000000000000000000000002"},
        {"logical_unit_id": "0x0000000000000003"},
        {"scsi_sas_port_0": {"phy_0": {"sas_address": "0x5000cca000000004"}}},
        {"scsi_sas_port_0": {"phy_1": {"attached_sas_address": "0x0"}}},
    ],
)
def test_the_guard_accepts_placeholders(document: object) -> None:
    assert list(identifier_problems(document)) == []


def test_every_fixture_has_a_recorded_source() -> None:
    # Every directory of fixtures is named in SOURCES.md, below the section of
    # its kind (NFR-20).
    sources = SOURCES.read_text(encoding="utf-8")
    for path in fixture_files():
        parts = path.parent.relative_to(FIXTURES).parts
        assert f"`{parts[0]}/`" in sources, parts[0]
        assert "`" + "/".join(parts[1:]) + "`" in sources, path


def imported_recordings() -> list[Path]:
    """Return the `recording.json` of every fixture taken from another project."""
    return [
        path
        for path in sorted(FIXTURES.rglob("recording.json"))
        if "source" in json.loads(path.read_text(encoding="utf-8"))
    ]


def test_there_are_imported_recordings_to_check() -> None:
    assert len(imported_recordings()) >= 10


@pytest.mark.parametrize(
    "path", imported_recordings(), ids=lambda path: str(path.parent.relative_to(FIXTURES))
)
def test_an_imported_recording_keeps_the_license_of_its_source(path: Path) -> None:
    # MIT and Apache-2.0 ask that the license text goes with the data
    # (ADR 0026); it is kept below tests/fixtures/licenses.
    recording = json.loads(path.read_text(encoding="utf-8"))
    source = recording["source"]

    license_file = REPOSITORY / source["license_file"]
    assert license_file.is_file(), source["license_file"]
    assert license_file.parent == FIXTURES / "licenses"
    # The file is named after the project and the license it holds.
    assert license_file.name.endswith(f"-{LICENSE_TEXTS[recording['license']]}.txt")
    assert source["repository"].startswith("https://")
    assert re.fullmatch(r"[0-9a-f]{40}", source["commit"])
    assert source["copyright"].startswith("Copyright")
    # Every file of the fixture names the file of the source it was made of.
    assert set(source["paths"]) == {entry["file"] for entry in recording["files"]}
