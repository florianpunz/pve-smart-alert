# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the two configuration files the package ships (ADR 0011).

They are the only files of the tool that an administrator reads without having
asked for them: the configuration file that is installed as a conffile and the
reference next to the documentation. The reference cannot drift from the
program, because what it documents is compared with the schema and the check
catalog here.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pve_smart_alert.checks import CATALOG, Check
from pve_smart_alert.config import _SCHEMA, TOOL_CHECK_IDS, Config, load_config
from pve_smart_alert.paths import REFERENCE_PATH

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG = REPOSITORY / "config" / "config.toml"
REFERENCE = REPOSITORY / "config" / "config.reference.toml"


def documented_keys(path: Path) -> dict[str, set[str]]:
    """Return the sections of a TOML file with the keys below each of them."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {section: set(keys) for section, keys in document.items()}


def documented_checks(path: Path) -> dict[str, set[str]]:
    """Return the check sections of the reference with the keys below each of them."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {name: set(table) for name, table in document.get("checks", {}).items()}


def documented_keys_of(check: Check) -> set[str]:
    """Return the keys of a check table that have a default to document."""
    keys = {"enabled"}
    # The confirmation count is documented where it differs from 1; the
    # comment above the checks says that every condition takes it.
    if check.confirm_runs != 1:
        keys.add("confirm_runs")
    defaults = list(check.per_class.values()) if check.per_class is not None else [check.thresholds]
    for thresholds in defaults:
        if thresholds is None:
            continue
        for severity in ("notice", "warning", "critical"):
            if getattr(thresholds, severity) is not None:
                keys.add(severity)
    return keys


def test_the_shipped_configuration_is_only_a_header() -> None:
    # Nothing but comments: every setting keeps its default, so an upgrade
    # raises no configuration prompt for an administrator who edited the file
    # (ADR 0011).
    assert documented_keys(CONFIG) == {}
    assert load_config(CONFIG) == Config(source=CONFIG)


def test_the_shipped_configuration_points_to_the_reference() -> None:
    # The file is only useful if it says where the keys are written down.
    assert "config.reference.toml" in CONFIG.read_text(encoding="utf-8")


def test_the_reference_is_installed_at_the_path_the_tool_names() -> None:
    # dh_compress compresses a file below /usr/share/doc that is larger than
    # 4 KiB unless debian/rules excludes it, so the reference would be
    # installed as config.reference.toml.gz, a path that neither `doctor`,
    # the shipped configuration nor the documentation names (ADR 0011).
    install = (REPOSITORY / "debian" / "pve-smart-alert.install").read_text(encoding="utf-8")
    directory = REFERENCE_PATH.parent.relative_to("/")
    assert re.search(rf"^config/{REFERENCE_PATH.name}\s+{directory}$", install, re.MULTILINE)
    rules = (REPOSITORY / "debian" / "rules").read_text(encoding="utf-8")
    assert re.search(r"^override_dh_compress:\n\tdh_compress\b.*\s-X\.toml$", rules, re.MULTILINE)


def test_the_reference_documents_every_key_of_the_program() -> None:
    sections = documented_keys(REFERENCE)
    assert {name: keys for name, keys in sections.items() if name != "checks"} == {
        section: set(keys) for section, keys in _SCHEMA.items()
    }
    document = tomllib.loads(REFERENCE.read_text(encoding="utf-8"))
    assert set(document["notify"]["reminder"]) == {"critical", "warning", "notice"}
    # Every check of the catalog has its section, with exactly the keys that
    # have a default; the keys a check accepts are a superset of them, and a
    # severity without a default has no value to document (ADR 0011).
    # The conditions of the tool have their section as well, with the enabled
    # state, the only key they take (ADR 0031).
    assert sections["checks"] == set(CATALOG) | TOOL_CHECK_IDS
    documented = documented_checks(REFERENCE)
    assert documented == {
        **{check.id: documented_keys_of(check) for check in CATALOG.values()},
        **{name: {"enabled"} for name in TOOL_CHECK_IDS},
    }
    for check in CATALOG.values():
        assert documented[check.id] <= check.settable
    # The per-drive overrides are documented as a commented example, because
    # a real entry would select a drive.
    assert "[[drive]]" in REFERENCE.read_text(encoding="utf-8")


def test_the_reference_holds_the_defaults() -> None:
    # Copying the reference over the configuration file must change nothing.
    # An override that repeats the built-in default is dropped when the file
    # is loaded, so the reference loads as the defaults.
    assert load_config(REFERENCE) == Config(source=REFERENCE)
