# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from pve_smart_alert.config import (
    Config,
    ConfigError,
    Detail,
    DiscoverySettings,
    ManualDevice,
    SmartctlSettings,
    TransportName,
    load_config,
)


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
    path = write_config(tmp_path, "[policy]\nreminder = 30\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == "policy"
    assert "unknown section [policy]" in str(error.value)


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


# [smartctl] (ADR 0004)


def test_the_smartctl_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.toml")

    assert config.smartctl == SmartctlSettings(
        path=Path("/usr/sbin/smartctl"), timeout_seconds=30.0, detail=Detail.EXTENDED
    )


def test_the_smartctl_section_can_be_set(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[smartctl]\npath = "/opt/test/fake-smartctl"\ntimeout = "2m"\ndetail = "basic"\n',
    )

    assert load_config(path).smartctl == SmartctlSettings(
        path=Path("/opt/test/fake-smartctl"), timeout_seconds=120.0, detail=Detail.BASIC
    )


@pytest.mark.parametrize(("text", "seconds"), [("1s", 1.0), ("45s", 45.0), ("15m", 900.0)])
def test_a_timeout_is_a_duration_with_a_unit(tmp_path: Path, text: str, seconds: float) -> None:
    path = write_config(tmp_path, f'[smartctl]\ntimeout = "{text}"\n')

    assert load_config(path).smartctl.timeout_seconds == seconds


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ('"30"', 'must be a duration such as "30s" or "2m", found "30"'),
        ('"half a minute"', "must be a duration"),
        ("30", "must be a string, found int"),
        ('"0s"', 'must be between 1s and 15m, found "0s"'),
        ('"1h"', 'must be between 1s and 15m, found "1h"'),
        ('"never"', "must be a duration"),
    ],
)
def test_a_timeout_that_is_not_one_is_an_error(tmp_path: Path, value: str, message: str) -> None:
    path = write_config(tmp_path, f"[smartctl]\ntimeout = {value}\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == "smartctl.timeout"
    assert message in str(error.value)
    assert error.value.line == 2


def test_the_path_of_smartctl_must_be_absolute(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[smartctl]\npath = "smartctl"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == "smartctl.path"
    assert "must be an absolute path" in str(error.value)


def test_an_unknown_detail_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[smartctl]\ndetail = "everything"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == "smartctl.detail"
    assert '"extended", "basic"' in str(error.value)


# [[discovery.device]] (FR-104)


def test_there_are_no_manual_devices_by_default(tmp_path: Path) -> None:
    assert load_config(tmp_path / "config.toml").discovery == DiscoverySettings()


def test_manual_devices_are_read_in_their_order(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        "[[discovery.device]]\n"
        'name = "/dev/sg3"\n'
        'type = "areca,2/1"\n'
        "\n"
        "[[discovery.device]]\n"
        'name = "/dev/bus/0"\n'
        'type = "sat+megaraid,12"\n',
    )

    assert load_config(path).discovery.devices == (
        ManualDevice(name="/dev/sg3", type="areca,2/1"),
        ManualDevice(name="/dev/bus/0", type="sat+megaraid,12"),
    )


@pytest.mark.parametrize(
    ("entry", "key", "message"),
    [
        ('name = "/dev/sdz"', "discovery.device.type", 'number 1 needs "type"'),
        ('type = "sat"', "discovery.device.name", 'number 1 needs "name"'),
        ('name = "/dev/sdz"\ntype = "sat"\nlabel = "x"', "discovery.device.label", "unknown key"),
        ('name = "sdz"\ntype = "sat"', "discovery.device.name", "must be a device below /dev"),
        (
            'name = "/dev/../etc/passwd"\ntype = "sat"',
            "discovery.device.name",
            "must be a device below /dev",
        ),
        ('name = "/dev/sdz"\ntype = "-T permissive"', "discovery.device.type", "device type"),
        ('name = "/dev/sdz"\ntype = "sat;reboot"', "discovery.device.type", "device type"),
        ('name = "/dev/sdz"\ntype = 3', "discovery.device.type", "must be a string"),
    ],
)
def test_a_manual_device_that_is_not_one_is_an_error(
    tmp_path: Path, entry: str, key: str, message: str
) -> None:
    path = write_config(tmp_path, f"[[discovery.device]]\n{entry}\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.key == key
    assert message in str(error.value)


def test_manual_devices_must_be_tables(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[discovery]\ndevice = ["/dev/sdz"]\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "written as [[discovery.device]]" in str(error.value)


def test_the_exclude_rules_are_not_read_yet(tmp_path: Path) -> None:
    # They arrive with the filtering of discovery.
    path = write_config(tmp_path, '[discovery]\nexclude = [{ model = "QEMU HARDDISK" }]\n')

    with pytest.raises(ConfigError, match='unknown key "exclude"'):
        load_config(path)
