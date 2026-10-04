# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the two configuration files the package ships (ADR 0011).

They are the only files of the tool that an administrator reads without having
asked for them: the configuration file that is installed as a conffile and the
reference next to the documentation. The reference cannot drift from the
program, because what it documents is compared with the schema here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pve_smart_alert.config import _SCHEMA, NotifySettings, load_config

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG = REPOSITORY / "config" / "config.toml"
REFERENCE = REPOSITORY / "config" / "config.reference.toml"


def documented_keys(path: Path) -> dict[str, set[str]]:
    """Return the sections of a TOML file with the keys below each of them."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {section: set(keys) for section, keys in document.items()}


def test_the_shipped_configuration_is_only_a_header() -> None:
    # Nothing but comments: every setting keeps its default, so an upgrade
    # raises no configuration prompt for an administrator who edited the file
    # (ADR 0011).
    assert documented_keys(CONFIG) == {}
    assert load_config(CONFIG).notify == NotifySettings()


def test_the_shipped_configuration_points_to_the_reference() -> None:
    # The file is only useful if it says where the keys are written down.
    assert "config.reference.toml" in CONFIG.read_text(encoding="utf-8")


def test_the_reference_documents_every_key_of_the_program() -> None:
    assert documented_keys(REFERENCE) == {section: set(keys) for section, keys in _SCHEMA.items()}


def test_the_reference_holds_the_defaults() -> None:
    # Copying the reference over the configuration file must change nothing.
    assert load_config(REFERENCE).notify == NotifySettings()
