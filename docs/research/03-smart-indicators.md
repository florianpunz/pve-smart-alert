# Research 03: Failure indicators and `smartctl --json` across SATA, SAS and NVMe

- Research date: 2026-10-03
- Applies to: smartmontools 7.4 (shipped with Proxmox VE 9), with notes on 7.0 to 7.5.
- Used by: [ADR 0004](../adr/0004-smartctl-json-as-data-source.md), [ADR 0010](../adr/0010-health-evaluation-and-default-thresholds.md)

## Summary

- For hard disks, five raw counters carry most of the predictive value: reallocated sectors (5), reported uncorrectable errors (187), command timeouts (188), current pending sectors (197) and offline uncorrectable sectors (198).
- SMART cannot predict every failure. Between a quarter and a third of failed drives showed no warning sign at all. A drive that stops answering must therefore be detected separately.
- Vendor thresholds on normalized values are set so low that they confirm a failure rather than predict one. The raw counters need their own thresholds.
- NVMe has a small, standardized health log. SAS has standardized log pages with different semantics. ATA attributes are vendor-defined. The three need separate parsers and separate checks.
- Temperature is a weak predictor of failure but a good indicator of a cooling problem.

## Evidence for hard disks

**Verified** in the cited publications.

Backblaze (2016) uses five attributes:

| ID | Attribute |
| --- | --- |
| 5 | Reallocated Sectors Count |
| 187 | Reported Uncorrectable Errors |
| 188 | Command Timeout |
| 197 | Current Pending Sector Count |
| 198 | Uncorrectable Sector Count |

- 76.7 % of failed drives had at least one of these raw values above zero, against 4.2 % of operational drives.
- 23.3 % of failed drives showed no warning in these attributes.

Google (Pinheiro, Weber, Barroso, FAST 2007):

- After the first scan error a drive is 39 times more likely to fail within 60 days. After the first reallocation: 14 times. After the first offline reallocation: 21 times. After the first probational (pending) count: 16 times.
- More than 36 % of failed drives had zero counts in all SMART variables.
- "Very little correlation between failure rates and either elevated temperature or activity levels."
- Conclusion: SMART data alone is unlikely to be sufficient to predict failures of individual drives.

Observed annual failure rates per raw value, compiled from Backblaze data by the Scrutiny project (MIT license). Rates above 100 % mean that drives in this bucket fail within less than a year on average.

| Attribute | Raw value → observed annual failure rate |
| --- | --- |
| 5 Reallocated sectors | 0 → 2.5 %; 1–4 → 2.7 %; 4–16 → 7.5 %; 16–70 → 23.6 %; 70–260 → 36 %; 260–1100 → 57 %; above → >150 % |
| 187 Reported uncorrectable | 0 → 2.8 %; 1 → 34 %; 1–3 → 24 %; 3–6 → 50 %; 6–11 → 38 %; 11–20 → 53 %; 20–35 → 84 %; above → >140 % |
| 188 Command timeout | 0–100 → 2.5 %; above 100 → 10 % and more |
| 197 Current pending | 0 → 2.6 %; 1–2 → 34 %; 2–6 → 68 %; 6–16 → 61 %; 16–40 → 96 %; above → >165 % |
| 198 Offline uncorrectable | 0 → 2.9 %; up to 2 → 81 %; 2–6 → >110 %; above → 58 % to 264 % |

Reading:

- A handful of reallocated sectors barely changes the failure rate. The rate triples from about 5 and rises sharply from about 16.
- A single pending, offline-uncorrectable or reported-uncorrectable sector moves the drive into a group that fails more than ten times as often.
- Command timeouts matter only above about 100.

Scrutiny additionally treats spin retries (10), end-to-end errors (184), reallocation events (196) and soft read errors (201) as critical attributes.

Limits of this evidence:

- The rates are partly circular. Backblaze counts a drive as failed not only when it is dead or unreadable, but also when it is replaced in advance because these five SMART values suggest an impending failure (Backblaze, 2014). Drives with high values are therefore removed, and counted as failures, by policy. The table overstates the risk for exactly these attributes. **Verified.**
- The data comes from hard disks. For SATA SSDs no comparable public table was found. Reallocated blocks on an SSD have a different meaning and scale. **Open question.**
- Some raw values are packed. Seagate drives store several 16-bit counters in the raw value of attribute 188 and of attributes 1 and 7. The numeric raw value is then huge although the drive is healthy. Raw values of 1 and 7 must never be compared with a threshold; 188 needs decoding. **Assumed** from general knowledge of the smartmontools drive database; to be verified with fixtures.
- UDMA CRC errors (199) are cumulative and almost always a cable or backplane problem. An old non-zero value says nothing about today. Only an increase is meaningful.

## SSD wear and spare

- SATA: there is no standard attribute. Vendors use different IDs and names (177 Wear_Leveling_Count, 202 Percent_Lifetime_Remain, 231 SSD_Life_Left, 233 Media_Wearout_Indicator and others). The normalized value usually counts down from 100. Proxmox VE's web interface uses a name list for this ([Research 02](02-builtin-smart-handling.md)). Using the same list keeps PVE SMART Alert consistent with the "Wearout" column. The recordings of [Research 06](06-test-cluster-recordings.md) show a drive for which this attribute is wrong; [ADR 0021](../adr/0021-wear-value-source.md) therefore makes the list the last source.
- SATA, vendor-neutral: the ATA Device Statistics log contains "Percentage Used Endurance Indicator". It needs `smartctl -x` or `-l devstat`. The JSON key layout of this log is **Assumed** and must be confirmed with fixtures.
- smartmontools 7.5 adds the vendor-neutral JSON values `endurance_used` (ATA, SCSI, NVMe) and `spare_available` (ATA, NVMe). **Verified** in the 7.5 release notes. Proxmox VE 9 ships 7.4, so these keys cannot be relied on yet. They can be used when present. Update 2026-10-05: Proxmox VE 9.2 ships 7.5 ([Research 06](06-test-cluster-recordings.md)).
- NVMe: `percentage_used` is a vendor estimate of consumed endurance. The specification allows values above 100 and states that 100 means the estimated endurance is consumed "but may not indicate an NVM subsystem failure". `available_spare` with `available_spare_threshold` is the actual failure signal.
- SAS SSDs: `scsi_percentage_used_endurance_indicator`. **Verified** to exist in 7.4 output (smartctl_exporter issue 347).

A real-world consequence (**Reported**, Proxmox forum): an NVMe drive above 100 % used sets Critical Warning bit 2 and is reported as failed every day although it keeps working. Wear must be a planning signal, and a known condition must be silenceable per drive.

## NVMe health log

Fields of the SMART / Health Information log as they appear under `nvme_smart_health_information_log` (**Verified** against a recorded 7.1 output):

`critical_warning`, `temperature`, `available_spare`, `available_spare_threshold`, `percentage_used`, `data_units_read`, `data_units_written`, `host_reads`, `host_writes`, `controller_busy_time`, `power_cycles`, `power_on_hours`, `unsafe_shutdowns`, `media_errors`, `num_err_log_entries`, `warning_temp_time`, `critical_comp_time`.

Critical Warning bits according to the NVMe Base Specification (**Assumed** from the specification text; not re-read on the research date):

| Bit | Meaning |
| --- | --- |
| 0 | Available spare has fallen below the threshold |
| 1 | Temperature above an over-temperature or below an under-temperature threshold |
| 2 | Reliability degraded due to significant media-related errors or an internal error |
| 3 | Media has been placed in read-only mode |
| 4 | Volatile memory backup device has failed |
| 5 | Persistent Memory Region has become read-only or unreliable |

Indicator quality:

| Field | Use |
| --- | --- |
| `critical_warning` | Strong. Evaluate per bit, because the bits mean very different things. |
| `available_spare` vs. threshold | Strong. |
| `media_errors` | Strong. Unrecovered data integrity errors. |
| `percentage_used` | Planning signal, not a failure signal. |
| `critical_comp_time`, `warning_temp_time` | Good for detecting thermal excursions between two checks, because they accumulate. |
| `num_err_log_entries` | Weak. Many drives log harmless entries for unsupported commands. smartctl 7.4 itself can increment this counter: reading the self-test log through a namespace device fails on some single-namespace drives and every failed attempt adds an error log entry (smartmontools issue 217, fixed after 7.4). |
| `unsafe_shutdowns` | Not a health indicator. |

Consequences for PVE SMART Alert:

- Query the NVMe controller device (`/dev/nvme0`, as `smartctl --scan` reports it), never the namespace block device.
- Do not alert on `num_err_log_entries` by default.

## SAS / SCSI

**Verified** against a recorded output and the 7.3 and 7.4 release notes:

- Health: `smart_status.passed`, derived from the informational exceptions log page.
- `scsi_grown_defect_list`: number of defects found after manufacturing. The counterpart to reallocated sectors.
- `scsi_error_counter_log` with `read`, `write` and `verify` sections, each with `errors_corrected_by_eccfast`, `errors_corrected_by_eccdelayed`, `errors_corrected_by_rereads_rewrites`, `total_errors_corrected`, `correction_algorithm_invocations`, `gigabytes_processed`, `total_uncorrected_errors`. Corrected errors are normal and can be in the hundreds of millions. Only `total_uncorrected_errors` is a failure indicator.
- `temperature.current` and `temperature.drive_trip`.
- `scsi_percentage_used_endurance_indicator` for SSDs.
- 7.3 added many SCSI JSON values and the pending defects log.

No public failure-rate table was found for grown defects. The Scrutiny test data contains a drive with 43 000 power-on hours and 56 grown defects that still passes its health check. Thresholds for SAS are therefore less well founded than for SATA. **Open question.**

## How the JSON differs per protocol

Common to all (**Verified** in recorded outputs):

- `json_format_version`, `smartctl.version`, `smartctl.exit_status`, `smartctl.messages[]` (if any)
- `device.name`, `device.info_name`, `device.type`, `device.protocol` (`ATA`, `SCSI`, `NVMe`)
- `model_name`, `serial_number`, `firmware_version`, `user_capacity.bytes`
- `smart_status.passed`
- `temperature.current`, `power_on_time.hours`, `power_cycle_count`

| | ATA / SATA | SCSI / SAS | NVMe |
| --- | --- | --- | --- |
| Identity extras | `wwn`, `rotation_rate` (0 = SSD), `form_factor` | `vendor`, `product`, `revision`, `rotation_rate`, `device_type` | `nvme_pci_vendor`, `nvme_ieee_oui_identifier`, `nvme_namespaces[]` |
| Main data | `ata_smart_attributes.table[]` with `id`, `name`, `value`, `worst`, `thresh`, `when_failed`, `flags`, `raw.value`, `raw.string` | `scsi_grown_defect_list`, `scsi_error_counter_log`, `scsi_percentage_used_endurance_indicator` | `nvme_smart_health_information_log` |
| Error log | `ata_smart_error_log` | – | NVMe error information log (7.4: with messages) |
| Self-test log | `ata_smart_self_test_log` | SCSI self-test results | NVMe self-test log (since 7.4) |
| Extra with `-x` | Device statistics, SCT status and temperature history, SATA PHY counters | Background scan, SAS PHY, defects, environmental reports, general statistics | `-x` equals `-a` |
| Missing | No standard wear value before 7.5 | No attribute table | No attribute table |

`-a` and `-x` (**Verified** in `smartctl(8)`):

- ATA: `-x` adds, among others, `-l xerror`, `-l devstat`, `-l scttemp`, `-l sataphy`.
- SCSI: `-x` adds `-l background`, `-l sasphy`, `-l defects`, `-l envrep`, `-l genstats`, `-l ssd`.
- NVMe: `-x` and `-a` are identical.

Exit status of smartctl, a bit mask (**Verified**):

| Bit | Meaning | Handling in PVE SMART Alert |
| --- | --- | --- |
| 0 | Command line did not parse | Tool error |
| 1 | Device open failed, no identify data, or device in low-power mode | Drive unreadable or in standby |
| 2 | A SMART or ATA command failed, or checksum error | Not fatal on its own; common with `-x` on drives that lack a log |
| 3 | SMART status is "DISK FAILING" | Finding |
| 4 | Prefail attributes at or below threshold | Finding |
| 5 | Attributes at or below threshold in the past | Informational |
| 6 | Error log contains records | Informational; only an increase counts |
| 7 | Self-test log contains errors | Finding |

Power mode: `-n standby` makes smartctl exit before any check if an ATA drive is in standby or sleep, by default with exit status 2. 7.5 adds `power_mode.*` to the JSON. How 7.4 reports this case in JSON is **Assumed** and must be captured as a fixture.

## Version notes

| Version | Relevant change | Source |
| --- | --- | --- |
| 7.0 | First release with `--json` | smartctl_exporter README |
| 7.3 | Many SCSI/SAS JSON additions, pending defects log | Release notes |
| 7.4 | NVMe self-tests and self-test log, NVMe error log messages, Seagate FARM log, SCSI general statistics | Release notes |
| 7.5 | JSON `endurance_used`, `spare_available`, `power_mode`; NVMe health per namespace; fix for self-test log on single-namespace NVMe devices | Release notes |

Proxmox VE 9.1 reports `smartmontools: 7.4-pve1` (**Reported**, forum). The latest upstream release is 7.5 (2025).

## Sources

- Backblaze, "What SMART Stats Tell Us About Hard Drives" (2016-10-06): <https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/>
- Backblaze, "Hard Drive SMART Stats" (2014-11-12), with the definition of a failed drive: <https://www.backblaze.com/blog/hard-drive-smart-stats/>
- Pinheiro, Weber, Barroso, "Failure Trends in a Large Disk Drive Population", FAST 2007: <https://static.googleusercontent.com/media/research.google.com/en//archive/disk_failures.pdf>
- Scrutiny attribute metadata with observed failure rates (MIT): <https://github.com/AnalogJ/scrutiny/blob/master/webapp/backend/pkg/thresholds/ata_attribute_metadata.go>
- Scrutiny recorded outputs: <https://github.com/AnalogJ/scrutiny/tree/master/webapp/backend/pkg/models/testdata>
- `smartctl(8)`, smartmontools 7.4: <https://manpages.debian.org/trixie/smartmontools/smartctl.8.en.html>
- smartmontools releases 7.3, 7.4, 7.5: <https://github.com/smartmontools/smartmontools/releases>
- smartmontools issue 217 (self-test log read increments the NVMe error counter): <https://github.com/smartmontools/smartmontools/issues/217>
- smartctl_exporter issue 347 (SCSI endurance indicator in JSON): <https://github.com/prometheus-community/smartctl_exporter/issues/347>
- NVM Express specifications: <https://nvmexpress.org/specifications/>
