# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the hardware support table of docs/hardware-support.md (NFR-16).

Every family carries one of the evidence labels of ADR 0016, and every
scenario the table names exists, so that the table and `make test` cannot
drift apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from scenarios import SCENARIOS

DOCUMENT: Final = Path(__file__).resolve().parents[2] / "docs" / "hardware-support.md"

#: The evidence labels of ADR 0016.
LABELS: Final = frozenset(
    {"Verified on hardware", "Verified by fixtures", "Experimental", "Not possible"}
)

#: The columns of the support table.
HEADER: Final = (
    "Family",
    "Driver",
    "How the tool reaches the drives",
    "Label",
    "Basis",
    "Scenario",
)


#: What the table writes for a family without a scenario.
NONE: Final = "\N{EN DASH}"


def rows() -> list[dict[str, str]]:
    """Return the rows of the support table, by column."""
    lines = DOCUMENT.read_text(encoding="utf-8").splitlines()
    table: list[str] = []
    for line in lines[lines.index("## Support table") + 1 :]:
        if line.startswith("|"):
            table.append(line)
        elif table:
            break
    header = tuple(cell.strip() for cell in table[0].strip("|").split("|"))
    assert header == HEADER
    result = []
    for line in table[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == len(HEADER), line
        result.append(dict(zip(HEADER, cells, strict=True)))
    return result


def named_scenarios() -> set[str]:
    """Return the scenarios the table names."""
    return {
        name.strip(" `")
        for family in rows()
        for name in family["Scenario"].split(",")
        if name.strip() != NONE
    }


def test_every_family_carries_an_evidence_label() -> None:
    families = rows()

    assert families
    for family in families:
        assert family["Label"] in LABELS, family["Family"]
        assert family["Basis"], family["Family"]


def test_every_named_scenario_exists() -> None:
    assert named_scenarios() <= set(SCENARIOS)


def test_every_scenario_is_in_the_table() -> None:
    # The two scenarios of milestone M4 show the notification policy on the
    # on-board drives, and the scenario `twenty-four-drives` shows the run
    # time of NFR-07 there; the table names them.
    assert set(SCENARIOS) <= named_scenarios()
