# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the check catalog and the evaluation of one snapshot (ADR 0010).

The snapshots are built by hand, so that every check can be shown on its
own, exactly at its thresholds (ADR 0016). The dry run against a recorded
host is tested in test_check_command.py.
"""

from __future__ import annotations

from dataclasses import replace

from pve_smart_alert.checks import (
    CATALOG,
    Thresholds,
    default_checks,
    evaluate,
)
from pve_smart_alert.config import (
    CheckOverride,
    Config,
    DriveOverride,
    DriveSelector,
    SelectorKind,
    effective_checks,
)
from pve_smart_alert.model import (
    CheckKind,
    Collection,
    DeviceAccess,
    DriveClass,
    DriveIdentity,
    FailingAttribute,
    Severity,
    Snapshot,
    WearSource,
)

IDENTITY = DriveIdentity.of("Samsung SSD 850 EVO 250GB", serial="ANON-SN-0001")
ACCESS = DeviceAccess("/dev/sda", "sat", "ATA")
COLLECTION = Collection(smartctl_version=(7, 5), exit_status=0)


def drive(
    drive_class: DriveClass = DriveClass.SSD,
    *,
    metrics: dict[str, int] | None = None,
    **kwargs: object,
) -> Snapshot:
    return Snapshot(
        identity=IDENTITY,
        access=ACCESS,
        drive_class=drive_class,
        collection=COLLECTION,
        metrics=metrics or {},
        **kwargs,  # type: ignore[arg-type]
    )


def checks_of(snapshot: Snapshot) -> dict[str, Severity]:
    return {finding.check: finding.severity for finding in evaluate(snapshot)}


# The model: applicability, missing data, severities (FR-301, FR-302, FR-206)


def test_a_healthy_drive_produces_no_findings() -> None:
    snapshot = drive(
        health_passed=True,
        smart_available=True,
        smart_enabled=True,
        last_self_test_passed=True,
        metrics={
            "temperature.current": 36,
            "wear.percent_used": 12,
            "ata.attr.5.raw": 0,
            "ata.attr.187.raw": 0,
            "ata.attr.197.raw": 0,
            "ata.attr.198.raw": 0,
            "ata.command_timeouts": 3,
            "ata.attr.199.raw": 2,
        },
    )

    assert evaluate(snapshot) == []


def test_a_check_without_input_is_not_applicable() -> None:
    # No metric, no flag: nothing is guessed (FR-206).
    snapshot = drive()

    assert evaluate(snapshot) == []


def test_a_check_of_another_class_is_not_applicable() -> None:
    # The wear check never sees a hard disk, the spin retries never a SSD.
    snapshot = drive(DriveClass.HDD, metrics={"wear.percent_used": 120})

    assert "wear" not in checks_of(snapshot)
    snapshot = drive(DriveClass.SSD, metrics={"ata.attr.10.raw": 5})
    assert "ata.spin_retries" not in checks_of(snapshot)


def test_every_finding_has_one_severity_and_the_check_names_its_source() -> None:
    snapshot = drive(metrics={"ata.attr.5.raw": 100})

    (finding,) = evaluate(snapshot)

    assert finding.severity is Severity.CRITICAL
    assert finding.kind is CheckKind.CONDITION
    assert finding.value == 100
    assert finding.threshold == 70
    assert "100 sectors" in finding.text


# All drives (docs/check-catalog.md)


def test_the_failed_health_verdict_is_critical() -> None:
    assert checks_of(drive(health_passed=False))["health.failed"] is Severity.CRITICAL


def test_the_health_verdict_is_not_used_for_nvme() -> None:
    # The verdict of an NVMe drive is the Critical Warning byte.
    snapshot = drive(DriveClass.NVME, health_passed=False)

    assert "health.failed" not in checks_of(snapshot)


def test_a_failed_self_test_is_a_warning() -> None:
    assert checks_of(drive(last_self_test_passed=False))["selftest.failed"] is Severity.WARNING


def test_switched_off_smart_is_a_notice_that_names_the_command() -> None:
    snapshot = drive(smart_available=True, smart_enabled=False)

    (finding,) = evaluate(snapshot)

    assert finding.severity is Severity.NOTICE
    assert "smartctl -s on /dev/sda" in finding.text


def test_the_temperature_limits_differ_per_class() -> None:
    assert (
        checks_of(drive(DriveClass.HDD, metrics={"temperature.current": 61}))["temperature"]
        is Severity.CRITICAL
    )
    assert (
        checks_of(drive(DriveClass.SSD, metrics={"temperature.current": 61}))["temperature"]
        is Severity.WARNING
    )
    assert (
        checks_of(drive(DriveClass.NVME, metrics={"temperature.current": 71}))["temperature"]
        is Severity.WARNING
    )
    assert "temperature" not in checks_of(drive(metrics={"temperature.current": 45}))


def test_the_critical_warning_bit_of_the_temperature_raises_a_warning() -> None:
    # Bit 1 of the Critical Warning byte, with bit 5 set as well: the
    # temperature is raised to a warning even though the current value is
    # far below the limit (docs/check-catalog.md).
    snapshot = replace(
        drive(DriveClass.NVME, metrics={"temperature.current": 40}),
        nvme_critical_warning=0b100010,
    )

    findings = evaluate(snapshot)

    assert {finding.check: finding.severity for finding in findings}["temperature"] is (
        Severity.WARNING
    )


def test_wear_never_becomes_critical_by_default() -> None:
    # FR-307: a worn drive is a warning, not a critical one.
    assert checks_of(drive(metrics={"wear.percent_used": 80}))["wear"] is Severity.NOTICE
    assert checks_of(drive(metrics={"wear.percent_used": 96}))["wear"] is Severity.WARNING
    assert "wear" not in checks_of(drive(metrics={"wear.percent_used": 79}))
    # Values above 100 % are legal for NVMe (ADR 0010).
    snapshot = drive(DriveClass.NVME, metrics={"wear.percent_used": 200})
    assert checks_of(snapshot)["wear"] is Severity.WARNING


def test_the_wear_finding_names_its_source() -> None:
    snapshot = drive(metrics={"wear.percent_used": 96}, wear_source=WearSource.ENDURANCE_USED)

    (finding,) = evaluate(snapshot)

    assert finding.text.startswith("96 % of the rated endurance used, from endurance_used")


# SATA (docs/check-catalog.md)


def test_a_pre_fail_attribute_below_its_threshold_is_critical() -> None:
    snapshot = drive(
        failing_attributes=(FailingAttribute(5, "Reallocated_Sector_Ct", prefailure=True),)
    )

    (finding,) = evaluate(snapshot)

    assert finding.check == "ata.attribute_failing"
    assert finding.severity is Severity.CRITICAL
    assert "5 (Reallocated_Sector_Ct)" in finding.text


def test_an_old_age_attribute_below_its_threshold_is_a_warning() -> None:
    snapshot = drive(failing_attributes=(FailingAttribute(187, "Reported_Uncorrect", False),))

    (finding,) = evaluate(snapshot)

    assert finding.severity is Severity.WARNING


def test_temperature_attributes_never_fail_the_attribute_check() -> None:
    # The well-known noise: a packed temperature value looks failing
    # (docs/check-catalog.md, Research 06).
    snapshot = drive(failing_attributes=(FailingAttribute(194, "Temperature_Celsius", True),))

    assert "ata.attribute_failing" not in checks_of(snapshot)


def test_the_defect_counters_use_their_thresholds() -> None:
    assert checks_of(drive(metrics={"ata.attr.5.raw": 1}))["ata.reallocated_sectors"] is (
        Severity.NOTICE
    )
    assert checks_of(drive(metrics={"ata.attr.5.raw": 5}))["ata.reallocated_sectors"] is (
        Severity.WARNING
    )
    assert checks_of(drive(metrics={"ata.attr.187.raw": 25}))["ata.reported_uncorrectable"] is (
        Severity.CRITICAL
    )
    assert checks_of(drive(metrics={"ata.attr.197.raw": 20}))["ata.pending_sectors"] is (
        Severity.CRITICAL
    )
    assert checks_of(drive(metrics={"ata.attr.198.raw": 12}))["ata.offline_uncorrectable"] is (
        Severity.CRITICAL
    )
    assert (
        checks_of(drive(DriveClass.HDD, metrics={"ata.attr.10.raw": 5}))["ata.spin_retries"]
        is Severity.WARNING
    )
    assert checks_of(drive(metrics={"ata.attr.184.raw": 2}))["ata.end_to_end_errors"] is (
        Severity.WARNING
    )
    assert checks_of(drive(metrics={"ata.command_timeouts": 600}))["ata.command_timeouts"] is (
        Severity.WARNING
    )
    # Up to 100 command timeouts are like clean drives (ADR 0010).
    assert "ata.command_timeouts" not in checks_of(drive(metrics={"ata.command_timeouts": 100}))


def test_an_event_without_a_baseline_produces_nothing() -> None:
    # FR-306: a counter that was never zero stays silent until it increases
    # against the baseline of the state file, which arrives with milestone M4.
    snapshot = drive(metrics={"ata.attr.199.raw": 3, "ata.error_log.count": 4})

    assert "ata.crc_errors" not in checks_of(snapshot)
    assert "ata.error_log" not in checks_of(snapshot)


# NVMe (docs/check-catalog.md)


def nvme(metrics: dict[str, int], *, critical_warning: int = 0) -> Snapshot:
    return drive(DriveClass.NVME, metrics=metrics, nvme_critical_warning=critical_warning)


def test_spare_at_or_below_the_threshold_of_the_drive_is_critical() -> None:
    snapshot = nvme({"nvme.available_spare": 4, "nvme.available_spare_threshold": 10})

    (finding,) = evaluate(snapshot)

    assert finding.check == "nvme.spare"
    assert finding.severity is Severity.CRITICAL


def test_spare_within_the_margin_is_a_warning() -> None:
    snapshot = nvme({"nvme.available_spare": 20, "nvme.available_spare_threshold": 10})

    (finding,) = evaluate(snapshot)

    assert finding.severity is Severity.WARNING
    assert "within 15 points" in finding.text


def test_a_drive_without_a_threshold_is_assumed_to_have_ten_percent() -> None:
    snapshot = nvme({"nvme.available_spare": 20})

    (finding,) = evaluate(snapshot)

    assert finding.severity is Severity.WARNING
    assert "the threshold of the drive, 10 %" in finding.text


def test_the_critical_warning_bits_have_their_severities() -> None:
    assert checks_of(nvme({}, critical_warning=0b100))["nvme.reliability_degraded"] is (
        Severity.CRITICAL
    )
    assert checks_of(nvme({}, critical_warning=0b1000))["nvme.read_only"] is Severity.CRITICAL
    assert checks_of(nvme({}, critical_warning=0b10000))["nvme.backup_failed"] is Severity.CRITICAL
    assert checks_of(nvme({}, critical_warning=0b100000))["nvme.pmr_unreliable"] is (
        Severity.WARNING
    )
    assert checks_of(nvme({"nvme.media_errors": 2}))["nvme.media_errors"] is Severity.WARNING


def test_the_nvme_error_log_is_disabled_by_default() -> None:
    snapshot = nvme({"nvme.error_log_entries": 50})

    assert evaluate(snapshot) == []


# SAS (docs/check-catalog.md): no parser produces these metrics until M6.


def test_the_scsi_checks_wait_for_a_parser() -> None:
    snapshot = drive(DriveClass.HDD, metrics={"scsi.grown_defects": 150})

    (finding,) = evaluate(snapshot)

    assert finding.check == "scsi.grown_defects"
    assert finding.severity is Severity.WARNING
    assert "scsi.uncorrected_errors" not in checks_of(snapshot)


def test_the_catalog_holds_the_identifiers_of_the_docs() -> None:
    # The identifiers are a public interface: they appear in configuration
    # files and must stay stable (ADR 0010).
    assert set(CATALOG) == {
        "health.failed",
        "selftest.failed",
        "temperature",
        "wear",
        "smart.disabled",
        "ata.attribute_failing",
        "ata.reallocated_sectors",
        "ata.reported_uncorrectable",
        "ata.command_timeouts",
        "ata.pending_sectors",
        "ata.offline_uncorrectable",
        "ata.spin_retries",
        "ata.end_to_end_errors",
        "ata.crc_errors",
        "ata.error_log",
        "nvme.spare",
        "nvme.reliability_degraded",
        "nvme.read_only",
        "nvme.backup_failed",
        "nvme.pmr_unreliable",
        "nvme.media_errors",
        "nvme.thermal_excursion",
        "nvme.error_log",
        "scsi.grown_defects",
        "scsi.uncorrected_errors",
        "scsi.pending_defects",
    }


# The effective settings of one drive (ARCHITECTURE.md section 6)


def settings_for(config: Config, snapshot: Snapshot) -> dict[str, Severity]:
    effective = effective_checks(config, snapshot.identity, snapshot.drive_class)
    return {finding.check: finding.severity for finding in evaluate(snapshot, effective)}


def test_a_global_override_moves_a_threshold() -> None:
    snapshot = drive(metrics={"ata.attr.5.raw": 3})
    config = Config(checks={"ata.reallocated_sectors": CheckOverride(warning=2)})

    assert settings_for(config, snapshot)["ata.reallocated_sectors"] is Severity.WARNING


def test_a_check_can_be_switched_off_globally() -> None:
    snapshot = drive(metrics={"ata.attr.5.raw": 100})
    config = Config(checks={"ata.reallocated_sectors": CheckOverride(enabled=False)})

    assert "ata.reallocated_sectors" not in settings_for(config, snapshot)


def test_a_per_class_override_reaches_its_class_only() -> None:
    config = Config(checks={"temperature": CheckOverride(warning={"ssd": 45})})
    warm_ssd = drive(metrics={"temperature.current": 46})
    warm_hdd = drive(DriveClass.HDD, metrics={"temperature.current": 46})

    assert settings_for(config, warm_ssd)["temperature"] is Severity.WARNING
    assert "temperature" not in settings_for(config, warm_hdd)


def test_a_per_drive_override_wins_over_the_global_one() -> None:
    snapshot = drive(metrics={"ata.attr.5.raw": 3})
    config = Config(
        checks={"ata.reallocated_sectors": CheckOverride(notice=5)},
        drives=(
            DriveOverride(
                selector=DriveSelector(SelectorKind.SERIAL, "ANON-SN-0001"),
                checks={"ata.reallocated_sectors": CheckOverride(notice=2)},
            ),
        ),
    )

    assert settings_for(config, snapshot)["ata.reallocated_sectors"] is Severity.NOTICE


def test_a_per_drive_override_can_exclude_a_check_for_one_drive() -> None:
    snapshot = drive(metrics={"ata.attr.5.raw": 100})
    other = Snapshot(
        identity=DriveIdentity.of("Another Drive", serial="ANON-SN-0009"),
        access=ACCESS,
        drive_class=DriveClass.SSD,
        collection=COLLECTION,
        metrics={"ata.attr.5.raw": 100},
    )
    config = Config(
        drives=(
            DriveOverride(
                selector=DriveSelector(SelectorKind.SERIAL, "ANON-SN-0001"),
                checks={"ata.reallocated_sectors": CheckOverride(enabled=False)},
            ),
        ),
    )

    assert "ata.reallocated_sectors" not in settings_for(config, snapshot)
    assert settings_for(config, other)["ata.reallocated_sectors"] is Severity.CRITICAL


def test_the_margin_of_the_spare_check_can_be_overridden() -> None:
    snapshot = nvme({"nvme.available_spare": 20, "nvme.available_spare_threshold": 10})
    config = Config(checks={"nvme.spare": CheckOverride(warning=5)})

    assert "nvme.spare" not in settings_for(config, snapshot)


def test_the_margin_of_the_spare_check_can_be_set_to_zero() -> None:
    # A configured 0 must not fall back to the default of 15 (FR-402).
    snapshot = nvme({"nvme.available_spare": 20, "nvme.available_spare_threshold": 10})
    config = Config(checks={"nvme.spare": CheckOverride(warning=0)})

    assert "nvme.spare" not in settings_for(config, snapshot)


def test_the_defaults_are_the_catalog() -> None:
    settings = default_checks(DriveClass.HDD)

    assert settings["temperature"].thresholds == Thresholds(warning=50, critical=60)
    assert settings["health.failed"].enabled
    assert settings["nvme.error_log"].enabled is False
    assert settings["wear"].check.classes == frozenset({DriveClass.SSD, DriveClass.NVME})
