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
    DriveSelector,
    ManualDevice,
    SelectorKind,
    SmartctlSettings,
    TransportName,
    drive_override,
    load_config,
    load_effective,
    load_last_good,
    save_last_good,
)
from pve_smart_alert.model import DriveIdentity


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

    assert "must be a list of tables, such as [[discovery.device]]" in str(error.value)


def test_the_exclude_rules_are_read(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        "[discovery]\n"
        "exclude = [\n"
        '    { model = "QEMU *" },\n'
        '    { serial = "S2R5NX0H123456A" },\n'
        '    { wwn = "0x5002538E40A1B2C3" },\n'
        "]\n",
    )

    assert load_config(path).discovery.exclude == (
        DriveSelector(SelectorKind.MODEL, "QEMU *"),
        DriveSelector(SelectorKind.SERIAL, "S2R5NX0H123456A"),
        DriveSelector(SelectorKind.WWN, "0x5002538E40A1B2C3"),
    )


def test_exclude_rules_can_be_written_as_tables(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[[discovery.exclude]]\nmodel = "QEMU HARDDISK"\n')

    assert load_config(path).discovery.exclude == (
        DriveSelector(SelectorKind.MODEL, "QEMU HARDDISK"),
    )


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ('{ model = "QEMU*", serial = "X" }', 'needs exactly one of "model", "serial", "wwn"'),
        ("{}", "needs exactly one of"),
        ('{ label = "boot" }', 'unknown key "label" in exclude rule number 1'),
        ('{ model = "" }', "must not be empty"),
        ('{ wwn = "not-hex" }', "must be hexadecimal digits"),
        ("{ serial = 12 }", "must be a string, found int"),
    ],
)
def test_an_exclude_rule_that_is_not_one_is_an_error(
    tmp_path: Path, rule: str, message: str
) -> None:
    path = write_config(tmp_path, f"[discovery]\nexclude = [{rule}]\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert message in str(error.value)


def test_exclude_rules_must_be_tables(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[discovery]\nexclude = ["QEMU HARDDISK"]\n')

    with pytest.raises(ConfigError, match="must be a list of tables"):
        load_config(path)


# The selectors of a drive (ADR 0024)


QEMU = DriveIdentity("QEMU HARDDISK", serial="QM00001")
SAMSUNG = DriveIdentity("Samsung SSD 850 EVO 250GB", serial="ANON-SN-0001", wwn="5002538000000001")


@pytest.mark.parametrize(
    ("pattern", "selected"),
    [
        ("QEMU HARDDISK", True),
        ("QEMU*", True),
        ("QEMU HARDDIS?", True),
        ("*HARDDISK", True),
        ("*", True),
        # The pattern matches the whole name.
        ("HARDDISK", False),
        ("QEMU", False),
        # Upper and lower case count.
        ("qemu*", False),
        # Only * and ? are special; brackets and dots mean themselves.
        ("QEMU [H]ARDDISK", False),
        ("QEMU.HARDDISK", False),
    ],
)
def test_a_model_is_a_pattern_with_star_and_question_mark(pattern: str, selected: bool) -> None:
    assert DriveSelector(SelectorKind.MODEL, pattern).matches(QEMU) is selected


def test_brackets_in_a_pattern_are_characters() -> None:
    drive = DriveIdentity("Odd [Model] 1")

    assert DriveSelector(SelectorKind.MODEL, "Odd [Model] ?").matches(drive)


def test_a_serial_number_is_compared_exactly() -> None:
    assert DriveSelector(SelectorKind.SERIAL, "ANON-SN-0001").matches(SAMSUNG)
    assert not DriveSelector(SelectorKind.SERIAL, "anon-sn-0001").matches(SAMSUNG)
    assert not DriveSelector(SelectorKind.SERIAL, "ANON-SN-000").matches(SAMSUNG)


def test_a_wwn_is_compared_in_its_digits() -> None:
    # The notations of the tool, lsblk and the web interface differ.
    for notation in ("5002538000000001", "0x5002538000000001", "0X5002538000000001"):
        assert DriveSelector(SelectorKind.WWN, notation).matches(SAMSUNG)
    assert not DriveSelector(SelectorKind.WWN, "5002538000000002").matches(SAMSUNG)
    assert not DriveSelector(SelectorKind.WWN, "5002538000000001").matches(QEMU)


# The check overrides of [checks."<id>"] (ADR 0011, FR-402)


def test_a_threshold_can_be_overridden_globally(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[checks."ata.reallocated_sectors"]\nwarning = 3\n')

    config = load_config(path)

    assert config.checks["ata.reallocated_sectors"].warning == 3


def test_a_check_can_be_switched_off(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[checks."ata.crc_errors"]\nenabled = false\n')

    config = load_config(path)

    assert config.checks["ata.crc_errors"].enabled is False


def test_a_check_that_is_off_by_default_can_be_switched_on(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[checks."nvme.error_log"]\nenabled = true\n')

    config = load_config(path)

    assert config.checks["nvme.error_log"].enabled is True


def test_an_unknown_check_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[checks."no.such_check"]\nenabled = false\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert 'unknown check "no.such_check"' in str(error.value)
    assert error.value.key == 'checks."no.such_check"'


def test_the_line_of_an_unknown_check_is_reported(tmp_path: Path) -> None:
    # The check names a section of its own, not a key on a line, so the line
    # has to be looked up in the form the section is written in.
    path = write_config(
        tmp_path, '[checks."wear"]\nenabled = false\n\n[checks."no.such_check"]\nenabled = false\n'
    )

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert error.value.line == 4
    assert str(error.value).endswith("(line 4)")


def test_a_key_the_check_does_not_have_is_an_error(tmp_path: Path) -> None:
    # A flag check has no thresholds; setting one would silently do nothing.
    path = write_config(tmp_path, '[checks."health.failed"]\nwarning = 5\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "this check accepts" in str(error.value)


def test_the_margin_of_the_spare_check_is_the_warning_threshold(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[checks."nvme.spare"]\nwarning = 20\n')

    config = load_config(path)

    assert config.checks["nvme.spare"].warning == 20
    # The critical verdict is the threshold of the drive itself, not a
    # number of the tool, so the check accepts no critical threshold.
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, '[checks."nvme.spare"]\ncritical = 5\n'))


def test_a_threshold_must_be_a_whole_number_of_zero_or_more(tmp_path: Path) -> None:
    for value in ('warning = "many"', "warning = true", "warning = -1", "warning = 1.5"):
        path = write_config(tmp_path, f'[checks."ata.pending_sectors"]\n{value}\n')
        with pytest.raises(ConfigError) as error:
            load_config(path)
        assert "whole number" in str(error.value)


def test_the_thresholds_of_the_temperature_can_be_set_per_class(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, '[checks."temperature"]\nwarning = { hdd = 48, ssd = 60, nvme = 70 }\n'
    )

    config = load_config(path)

    # The classes that keep their default are dropped, so that the override
    # holds only what differs from the built-in defaults.
    assert config.checks["temperature"].warning == {"hdd": 48}


def test_a_single_number_counts_for_every_class(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[checks."temperature"]\nwarning = 45\n')

    config = load_config(path)

    assert config.checks["temperature"].warning == 45


def test_a_table_of_classes_for_a_check_of_one_value_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[checks."ata.reallocated_sectors"]\nwarning = { hdd = 5 }\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "whole number" in str(error.value)


def test_a_class_the_check_does_not_accept_is_an_error(tmp_path: Path) -> None:
    # The temperature accepts the three class names, nothing else.
    path = write_config(tmp_path, '[checks."temperature"]\nwarning = { sata = 50 }\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert 'names the class "sata", which this check does not apply to' in str(error.value)


def test_an_override_that_repeats_the_default_is_dropped(tmp_path: Path) -> None:
    # The reference lists every key with its default, and loading it must
    # change nothing (ADR 0011).
    path = write_config(
        tmp_path,
        '[checks."ata.reallocated_sectors"]\nnotice = 1\nwarning = 5\ncritical = 70\n'
        '[checks."temperature"]\nwarning = { hdd = 50, ssd = 60, nvme = 70 }\n'
        '[checks."nvme.error_log"]\nenabled = false\n'
        '[checks."health.failed"]\nenabled = true\n',
    )

    config = load_config(path)

    assert config.checks == {}


# The per-drive overrides of [[drive]] (ADR 0011, FR-403)


def test_a_drive_entry_can_exclude_and_describe_a_drive(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[[drive]]\nserial = "ANON-SN-0001"\ncomment = "Worn, replacement ordered"\n'
        "exclude = true\n",
    )

    config = load_config(path)

    (entry,) = config.drives
    assert entry.selector == DriveSelector(SelectorKind.SERIAL, "ANON-SN-0001")
    assert entry.comment == "Worn, replacement ordered"
    assert entry.exclude is True


def test_a_drive_entry_can_name_another_detail_level(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, '[[drive]]\nmodel = "Samsung *"\ndetail = "basic"\nexclude = false\n'
    )

    config = load_config(path)

    assert config.drives[0].detail is Detail.BASIC
    assert config.drives[0].exclude is False


def test_a_drive_entry_needs_exactly_one_selector(tmp_path: Path) -> None:
    for content in (
        '[[drive]]\ncomment = "no selector"\n',
        '[[drive]]\nserial = "S1"\nmodel = "M"\n',
    ):
        path = write_config(tmp_path, content)
        with pytest.raises(ConfigError) as error:
            load_config(path)
        assert "exactly one of" in str(error.value)


def test_an_unknown_key_in_a_drive_entry_is_an_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[[drive]]\nserial = "S1"\nname = "/dev/sda"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert 'unknown key "name"' in str(error.value)


def test_a_drive_entry_can_override_a_check(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[[drive]]\nserial = "ANON-SN-0001"\n\n[drive.checks."wear"]\nenabled = false\n',
    )

    config = load_config(path)

    assert config.drives[0].checks["wear"].enabled is False


def test_an_unknown_check_in_a_drive_entry_is_an_error(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, '[[drive]]\nserial = "S1"\n\n[drive.checks."no.such_check"]\nenabled = false\n'
    )

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert 'unknown check "no.such_check"' in str(error.value)
    assert error.value.line == 4


def test_the_first_matching_drive_entry_wins(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[[drive]]\nmodel = "Samsung *"\n\n[drive.checks."wear"]\nenabled = false\n'
        '\n[[drive]]\nserial = "ANON-SN-0001"\n\n[drive.checks."wear"]\nenabled = true\n',
    )
    config = load_config(path)
    drive = DriveIdentity.of("Samsung SSD 850 EVO 250GB", serial="ANON-SN-0001")

    entry = drive_override(config, drive)

    assert entry is not None
    assert entry.checks["wear"].enabled is False


# The last good configuration (ADR 0011, FR-406)


def test_the_last_good_configuration_survives_a_round_trip(tmp_path: Path) -> None:
    from dataclasses import replace

    path = write_config(
        tmp_path,
        '[notify]\ntransport = "mail"\n\n[checks."temperature"]\nwarning = { hdd = 48 }\n'
        '\n[[drive]]\nserial = "ANON-SN-0001"\nexclude = true\n',
    )
    config = load_config(path)
    last_good = tmp_path / "last-good-config.json"

    save_last_good(config, last_good)
    loaded = load_last_good(last_good)

    assert loaded == replace(config, source=last_good)


def test_without_a_last_good_configuration_there_are_the_defaults(
    tmp_path: Path,
) -> None:
    assert load_last_good(tmp_path / "absent.json") is None

    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    assert load_last_good(tmp_path / "broken.json") is None


def test_an_invalid_file_leads_to_the_last_good_configuration(tmp_path: Path) -> None:
    path = write_config(tmp_path, '[notify]\ntransport = "mail"\n')
    last_good = tmp_path / "last-good-config.json"
    save_last_good(load_config(path), last_good)
    path.write_text("[notify]\ntimeout = 30\n", encoding="utf-8")

    config, error = load_effective(path, last_good=last_good)

    assert error is not None
    assert 'unknown key "timeout"' in str(error)
    assert config.notify.transport is TransportName.MAIL
    assert config.source == last_good


def test_without_a_last_good_configuration_an_invalid_file_leads_to_the_defaults(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path, "[notify]\ntransport = 30\n")

    config, error = load_effective(path, last_good=None)

    assert error is not None
    assert config == Config()


def test_the_last_good_configuration_is_saved_after_a_validation(tmp_path: Path) -> None:
    # The commands save it; here the save itself is the test.
    path = write_config(tmp_path, '[checks."wear"]\nwarning = 90\n')
    last_good = tmp_path / "last-good-config.json"

    save_last_good(load_config(path), last_good)

    loaded = load_last_good(last_good)
    assert loaded is not None
    assert loaded.checks["wear"].warning == 90
