# Check catalog

This is the living list of checks and their default thresholds.
The model and the reasoning are in [ADR 0010](adr/0010-health-evaluation-and-default-thresholds.md); the notification behavior of conditions and events is in [ADR 0009](adr/0009-notification-policy.md).

Status: **planned, provisional**. Nothing is implemented yet. The numbers are reviewed in milestone M3 of the [roadmap](../ROADMAP.md).

## How to read the tables

- **ID**: stable identifier, used in the configuration (`[checks."<id>"]`) and shown in notifications. Renaming an ID is a breaking change.
- **Kind**:
  - *condition*: a state that is active until it clears. Reminders and recovery apply.
  - *event*: an increase of a cumulative counter since the stored baseline. Reported, then the baseline moves.
- **N / W / C**: default thresholds for notice, warning and critical. "flag" means the check has one fixed severity and no number. "–" means the severity is not used.
- **Worsening**: *increase* means every further increase is reported, subject to the cool-down. *escalation* means only a change to a higher severity is reported.
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
- `temperature`: for SAS drives, critical is also raised at the drive's own trip temperature if it reports one. For NVMe, Critical Warning bit 1 raises at least a warning.
- `wear`, sources: NVMe `percentage_used`; the SAS endurance indicator; for SATA, the vendor attribute found through the same name list that the Proxmox VE web interface uses, so that both show the same number. If a SATA drive has no such attribute, the vendor-neutral value of smartmontools 7.5 or the ATA device statistics value is used.
- `selftest.failed` only reads logs. The tool never starts a self-test.

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
- `ata.command_timeouts`: the raw value is packed on some drives. The decoding rule is an open question.
- The thresholds were derived from hard disk data. They apply to SATA SSDs for lack of better data.

## NVMe

| ID | Source | Kind | N | W | C | Worsening |
| --- | --- | --- | --- | --- | --- | --- |
| `nvme.spare` | Available spare compared with the drive's own threshold | condition | – | threshold + 15 points or less | at or below threshold, or Critical Warning bit 0 | escalation |
| `nvme.reliability_degraded` | Critical Warning bit 2 | condition | – | – | flag | – |
| `nvme.read_only` | Critical Warning bit 3 | condition | – | – | flag | – |
| `nvme.backup_failed` | Critical Warning bit 4 | condition | – | – | flag | – |
| `nvme.pmr_unreliable` | Critical Warning bit 5 | condition | – | flag | – | – |
| `nvme.media_errors` | Media and data integrity errors | condition | – | 1 | – | increase |
| `nvme.thermal_excursion` | Time above the critical temperature increased | event | – | flag | – | – |
| `nvme.error_log` | Number of error log entries increased | event, **disabled by default** | flag | – | – | – |

Notes:

- If the drive reports no spare threshold, 10 % is assumed.
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

## Deliberately not checked

- Normalized attribute values against thresholds of the tool's own.
- Performance attributes.
- Power-on hours, power cycles, start-stop counts, unsafe shutdowns. They appear in notifications as context.
- The state of pools, arrays and logical volumes.
