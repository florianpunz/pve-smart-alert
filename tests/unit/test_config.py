# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from pve_smart_alert.config import Config, ConfigError, TransportName, load_config


def write_config(tmp_path: Path, content: str) -> Path:
    """Write a configuration file and return its path."""
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_a_missing_file_gives_the_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.toml")

    assert config == Config()
    assert config.notify.transport is TransportName.AUTO
    assert config.source is None


def test_an_empty_file_gives_the_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path, "")

    config = load_config(path)

    assert config.notify.transport is TransportName.AUTO
    assert config.source == path


def test_a_file_with_only_comments_gives_the_defaults(tmp_path: Path) -> None:
    # This is what the package ships (ADR 0011).
    path = write_config(tmp_path, "# See /usr/share/doc/pve-smart-alert/config.reference.toml\n")

    assert load_config(path).notify.transport is TransportName.AUTO


def test_the_transport_can_be_selected(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[notify]\ntransport = "mail"\n')

    config = load_config(path)

    assert config.notify.transport is TransportName.MAIL
    assert config.source == path


def test_the_primary_transport_can_be_selected(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[notify]\ntransport = "pve-notify"\n')

    assert load_config(path).notify.transport is TransportName.PVE_NOTIFY


def test_an_unknown_section_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, "[smartctl]\ntimeout = 30\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == "smartctl"
    assert "unknown section [smartctl]" in str(error.value)


def test_an_unknown_key_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, "[notify]\ntimeout = 30\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == "notify.timeout"
    assert 'unknown key "timeout" in section [notify]' in str(error.value)


def test_a_key_outside_a_section_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'transport = "mail"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert 'unknown key "transport"' in str(error.value)


def test_the_line_of_an_unknown_key_is_reported(tmp_path: Path) -> None:
    path = write_config(tmp_path, "# comment\n[notify]\ntimeout = 30\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.line == 3
    assert str(error.value).endswith("(line 3)")


def test_an_unknown_transport_value_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[notify]\ntransport = "carrier-pigeon"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == "notify.transport"
    assert '"auto", "pve-notify", "mail"' in str(error.value)


def test_a_wrong_type_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, "[notify]\ntransport = 5\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "must be a string, found int" in str(error.value)


def test_a_table_where_a_value_belongs_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[notify.transport]\nname = "mail"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "must be a string, found dict" in str(error.value)


def test_a_section_where_a_value_belongs_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[notify]\ntransport = { name = "mail" }\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "must be a string, found dict" in str(error.value)


def test_invalid_toml_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, "[notify\ntransport = \n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "not valid TOML" in str(error.value)


def test_a_file_that_is_not_utf8_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b'[notify]\ntransport = "\xff\xfe"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "not valid UTF-8" in str(error.value)
