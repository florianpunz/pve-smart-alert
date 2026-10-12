# Check catalog

This is the living list of checks and their default thresholds.
The model and the reasoning are in [ADR 0010](adr/0010-health-evaluation-and-default-thresholds.md); the notification behavior of conditions and events is in [ADR 0009](adr/0009-notification-policy.md).

The numbers are **provisional**. They were reviewed in milestone M3 of the [roadmap](../ROADMAP.md) against the recordings of the test cluster: the healthy drives of all three nodes stay below every threshold. The review is repeated as new recordings arrive; feedback that shows a default as too noisy or too quiet changes it without a new decision record, as long as the model and the principles hold.

The checks are implemented since milestone M3 (`src/pve_smart_alert/checks.py`), except where a note says otherwise.

## How to read the tables

- **ID**: stable identifier, used in the configuration (`[checks."<id>"]`) and shown in notifications. Renaming an ID is a breaking change.
- **Kind**:
  - *condition*: a state that is active until it clears. Reminders and recovery apply.
  - *event*: an increase of a cumulative counter since the baseline stored for the drive. Reported, then the baseline moves. A drive seen for the first time starts from its current values, so an old non-zero counter never alerts, and a counter below its baseline lowers it (FR-306).
- **N / W / C**: default thresholds for notice, warning and critical. "flag" means the check has one fixed severity and no number. "–" means the severity is not used by default; it can still be set in the configuration, except where a note says otherwise.
- **Worsening**: *increase* means every further increase at the same severity is reported, subject to the cool-down of the drive. *escalation* means only a change to a higher severity is reported. The notification planner applies it ([ARCHITECTURE.md](../ARCHITECTURE.md) section 7), and a test keeps this column and the catalog of the code in step.
- A check whose source value is missing is not applicable and produces nothing.

Drive classes: `hdd` and `ssd` (SATA or SAS, by rotation rate; unknown is treated as `hdd`), `nvme`.

## All drives

| ID | Applies to | Source | Kind | N | W | C | Worsening |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `health.failed` | SATA, SAS | Drive's own health verdict is "failed" | condition | – | – | flag | – |
| `selftest.failed` | all | Most recent self-test in the log ended with an error | condition | – | flag | – | – |
| `temperature` | all | Current temperature in °C | condition, confirmed in 2 runs | – | hdd 50, ssd 60, nvme 70 | hdd 60, ssd 70, nvme 80 | escalation |
| `wear` | ssd, nvme | Percentage of rated endurance used | condition | 80 | 95 | – | escalation |
| `smart.disabled` | SATA, SAS | SMART is available but switched off | condition | flag | – | – | – |
| `drive.unreadable` | all | No usable SMART data in 2 consecutive runs | condition | – | flag | – | – |
| `drive.missing` | all, except removable drives and drives without stable identity | Drive absent in 2 consecutive runs | event, once | – | flag | – | – |

Notes:

- `health.failed` is not used for NVMe. The NVMe verdict is the Critical Warning byte, which is evaluated bit by bit below.
- `temperature`: the limits of the drive itself are not read; the fixed limits per class apply until [Q-T4](../OPEN-QUESTIONS.md) is answered. For NVMe, Critical Warning bit 1 raises at least a warning. On hosts with smartmontools 7.4 the NVMe limits do not exist in the JSON at all ([Research 03](research/03-smart-indicators.md)).
- `wear`, sources in this order ([ADR 0021](adr/0021-wear-value-source.md)): `endurance_used` of smartmontools 7.5; then the ATA device statistics value, NVMe `percentage_used` or the SAS endurance indicator; then, for SATA only, the vendor attribute found through the name list of the Proxmox VE web interface, and last the same kind of guess made by smartmontools. The source used is shown with the value. For ATA, `endurance_used` counts as the first source only when the device statistics were read: without them smartmontools guesses it from a vendor attribute, and the guess is named for what it is ([Research 03](research/03-smart-indicators.md)); with `smartctl.detail = "basic"` the wear of an SSD therefore comes from a vendor attribute.
- `selftest.failed` only reads logs. The tool never starts a self-test.
- `drive.unreadable` and `drive.missing` are raised by the notification planner from consecutive runs, not from the data of a drive, and their counts are `notify.unreadable_runs` and `notify.missing_runs` (default 2). They accept only `enabled`. A device that never answered with a model and serial number is unreadable under its device name and type. While a drive is missing or unreadable, its other conditions are frozen: no reminders, no recovery.

## SATA (ATA attributes)

| ID | Attribute | Applies to | Kind | N | W | C | Worsening |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ata.attribute_failing` | Any attribute currently at or below its vendor threshold, except temperature attributes | hdd, ssd | condition | – | old-age attribute | pre-fail attribute | – |
| `ata.reallocated_sectors` | 5, raw | hdd, ssd | condition | 1 | 5 | 70 | increase |
| `ata.reported_uncorrectable` | 187, raw | hdd, ssd | condition | – | 1 | 20 | increase |
| `ata.command_timeouts` | 188, raw, decoded | hdd, ssd | condition | – | 100 | – | escalation |
| `ata.pending_sectors` | 197, raw | hdd, ssd | condition | – | 1 | 16 | increase |
| `ata.offline_uncorrectable` | 198, raw | hdd, ssd | condition | – | 1 | 10 | increase |
| `ata.spin_retries` | 10, raw | hdd | condition | – | 1 | – | increase |
| `ata.end_to_end_errors` | 184, raw | hdd, ssd | condition | – | 1 | – | increase |
| `ata.crc_errors` | 199, raw | hdd, ssd | event | flag | – | – | – |
| `ata.error_log` | Number of entries in the ATA error log | hdd, ssd | event | flag | – | – | – |

Notes:

- Raw values of attributes 1 (read error rate) and 7 (seek error rate) are never evaluated. They are packed on some vendors' drives.
- `ata.command_timeouts`: the raw value is packed on some drives; where the string form has several parts, the decoded first number counts (Q-T1). The threshold is met strictly above its value: up to 100 timeouts are what clean drives show.
- The thresholds were derived from hard disk data. They apply to SATA SSDs for lack of better data.
- The recordings of the test cluster show values a check must not misread: a worst value of 0 with a threshold of 0 on attribute 187, a packed raw value of the temperature attribute 194, and the placeholder temperature limits -127 and 127 ([Research 06](research/06-test-cluster-recordings.md#quirks-seen)).

## NVMe

| ID | Source | Kind | N | W | C | Worsening |
| --- | --- | --- | --- | --- | --- | --- |
| `nvme.spare` | Available spare compared with the drive's own threshold | condition | – | threshold + 15 points or less | at or below threshold, or Critical Warning bit 0 | escalation |
| `nvme.reliability_degraded` | Critical Warning bit 2 | condition | – | – | flag | – |
| `nvme.read_only` | Critical Warning bit 3 | condition | – | – | flag | – |
| `nvme.backup_failed` | Critical Warning bit 4 | condition | – | – | flag | – |
| `nvme.pmr_unreliable` | Critical Warning bit 5 | condition | – | flag | – | – |
| `nvme.media_errors` | Media and data integrity errors | condition | – | 1 | – | increase |
| `nvme.thermal_excursion` | Time above the critical temperature (`critical_comp_time`, minutes) increased | event | – | flag | – | – |
| `nvme.error_log` | Number of error log entries increased | event, **disabled by default** | flag | – | – | – |

Notes:

- If the drive reports no spare threshold, 10 % is assumed.
- `nvme.spare` accepts only `enabled` and `warning` in the configuration, and `warning` is the margin in points above the threshold of the drive, 15 by default. The critical verdict is the threshold of the drive itself, which the tool does not set.
- `nvme.error_log` is off because many drives log harmless entries, and reading logs can itself add entries on some drives with smartmontools 7.4.

## SAS (SCSI log pages)

| ID | Source | Kind | N | W | C | Worsening |
| --- | --- | --- | --- | --- | --- | --- |
| `scsi.grown_defects` | Elements in the grown defect list | condition | 1 | 100 | – | increase |
| `scsi.uncorrected_errors` | Sum of uncorrected read, write and verify errors | condition | – | 1 | – | increase |
| `scsi.pending_defects` | Pending defects | condition | – | 1 | – | increase |

Notes:

- Corrected errors are normal on SAS drives and are not evaluated.
- No public failure-rate data was found for these values. The defaults are the weakest in the catalog.
- No parser produces these metrics until milestone M6; the checks exist so that their identifiers are stable from now on, and they are never applicable until then.

## Conditions of the tool itself

These are reported like drive conditions, for a pseudo-device named `pve-smart-alert`.

| ID | Meaning | Severity |
| --- | --- | --- |
| `tool.smartctl_missing` | smartctl was not found or cannot be executed | critical |
| `tool.smartctl_too_old` | smartctl is older than 7.0 | critical |
| `tool.scan_failed` | The device scan failed or returned nothing usable | warning |
| `tool.config_invalid` | The configuration file is invalid; the last good configuration is in use | warning |
| `tool.state_reset` | The state file was unreadable and has been reset | notice |
| `tool.transport_degraded` | The primary notification transport failed; the fallback is in use | warning |
| `tool.unsupported_controller` | A controller is present whose drives cannot be queried | notice |

Notes:

- `tool.state_reset` is a one-time event. It is mentioned in the summary that follows the reset and has no recovery message.
- All others are conditions. They clear, with a recovery message, when the cause is gone.
- `tool_conditions.py` detects them at the start of a run since milestone M4, except `tool.unsupported_controller`, which arrives with milestone M6. `tool.smartctl_too_old` is read from the version of the device scan, or, when the scan writes no JSON, from the first line of `smartctl --version`, which starts with `smartctl 7.5` on `pve1` (smartmontools 7.5, checked on 2026-10-12). `tool.transport_degraded` holds when the notify bridge, asked to load the notification system without sending, fails; with `transport = mail` there is no bridge to fail.

## Deliberately not checked

- Normalized attribute values against thresholds of the tool's own.
- Performance attributes.
- Power-on hours, power cycles, start-stop counts, unsafe shutdowns. They appear in notifications as context.
- The state of pools, arrays and logical volumes.
