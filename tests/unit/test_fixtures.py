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
    return False


def _placeholder_wwn(value: object) -> bool:
    """Whether a WWN, as an object of smartctl or as text, has a counter as its number."""
    if isinstance(value, dict):
        return _small(value.get("id"))
    if not isinstance(value, str):
        return False
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
