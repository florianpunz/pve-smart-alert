# Research 08: Public recordings of SAS and RAID drives, and what smartctl writes for them

- Research date: 2026-10-16
- Applies to: smartmontools 7.4 and 7.5; the test data of other projects at the commits named below.
- Used by: [ADR 0026](../adr/0026-recordings-of-scsi-drives-and-of-other-projects.md), milestone M6 ([ROADMAP.md](../../ROADMAP.md))

## Summary

| Family | Usable real recording? | Imported as fixture |
| --- | --- | --- |
| SAS, directly attached | Yes, healthy SAS hard disks and SSDs (smartmontools 7.3). One SAS hard disk with grown defects, without the version of smartmontools | 7 recordings below `direct/` |
| Parallel SCSI | Yes, also one with grown defects and uncorrected errors (smartmontools 7.4) | 2 recordings below `direct/` |
| MegaRAID | Yes for SATA drives behind it (`sat+megaraid,N`) and for device scans. **No** real JSON of a SAS drive read as `megaraid,N` | 3 recordings below `megaraid/` |
| Logical volume of a RAID controller | One Intel RAID 1 volume read as a SCSI device (smartmontools 7.0). None of MegaRAID | 1 recording below `intel-rst/` |
| HPE Smart Array (`cciss,N`) | Only `--info` output whose license chain is unclear | None; evidence only |
| `mpi3mr` | None. smartmontools 7.5 has no code for it | None |

Two questions of the M6 plan are answered from the source code:

- **Non-medium errors have no JSON key.** smartctl writes the count only as text. A check for it would have to read text, which [ADR 0004](../adr/0004-smartctl-json-as-data-source.md) and FR-201 rule out. It is not checked.
- **`--xall` reads the pending defects log of a SCSI drive; `--all` does not.** The tool reads `--xall` by default (`smartctl.detail = "extended"`, [ADR 0004](../adr/0004-smartctl-json-as-data-source.md)), so `scsi_pending_defects.count` is there where the drive supports the log page, and missing with `smartctl.detail = "basic"`.

## Method

The source code of smartmontools was read at the tags `RELEASE_7_4` (commit `0c0bada5eedb759c9d7bb50ff54959cf0809c5a9`) and `RELEASE_7_5` (commit `f276b249fdc84019403491303479485030ac7c80`), in the files `scsiprint.cpp`, `smartctl.cpp`, `os_linux.cpp`, `json.cpp` and `json.h`.
Line numbers are given for both versions, because they differ in most places after line 1000.

The test data of other projects was searched in the repositories named in [Research 05](05-prior-art.md) and in projects found by searching for smartctl JSON test data.
Every file named below was read at the commit given, together with the license file of its repository.
Values that identify a drive are not quoted here; where a file has them, the field is named.

All statements are **Verified** in the cited source or file, unless marked otherwise.

## What smartctl writes for a SCSI drive

| Key | Meaning | `scsiprint.cpp` 7.4 | 7.5 |
| --- | --- | --- | --- |
| `smart_status.passed` | `false` with `smart_status.scsi.asc`, `ascq` and `ie_string` when the drive reports an informational exception; `true` only when the drive has the IEC mode page. Without the page the key is **absent** | 396–403 | 396–403 |
| `temperature.current`, `temperature.drive_trip` | Current temperature and the trip temperature of the drive | 411, 417 | 411, 417 |
| `scsi_grown_defect_list` | Number of elements in the grown defect list | 745, 753 | 745, 753 |
| `scsi_error_counter_log.read`, `.write`, `.verify` | Each with `errors_corrected_by_eccfast`, `errors_corrected_by_eccdelayed`, `errors_corrected_by_rereads_rewrites`, `total_errors_corrected`, `correction_algorithm_invocations`, `gigabytes_processed` (a string) and `total_uncorrected_errors` | 969–992 | 969–992 |
| `scsi_pending_defects.count` | Pending defects, from a log subpage that only some drives have | 620 | 620 |
| `scsi_percentage_used_endurance_indicator` | SSD endurance used, in percent | 1771 | 1771 |
| `endurance_used.current_percent` | The same value under the vendor-neutral key | – | 1772 |
| `logical_unit_id` | The name from the device identification page, `0x` and hexadecimal digits | 3081 | 3120 |
| `serial_number` | Serial number | 3099 | 3138 |
| `device_type.scsi_value`, `.name` | Peripheral device type; the table names value 12 `storage array` and 13 `enclosure` | 3111–3115, table 2734 | 3150–3154, table 2770 |
| `scsi_transport_protocol.name` | Such as `SAS (SPL-4)` or `Parallel SCSI (SPI-4)` | 3125 | 3164 |
| `scsi_vendor`, `scsi_product`, `scsi_model_name`, `scsi_revision` | Inquiry data | 2851–2859 | 2890–2898 |
| `scsi_sas_port_N.phy_M.sas_address`, `.attached_sas_address` | SAS addresses, `0x` and hexadecimal digits without leading zeros; only with the SAS phy log, which `--xall` reads | 2496, 2512, 2611, 2616 | 2532, 2548, 2647, 2652 |

How the keys are formed: `json::ref` turns every key with `json::str2key`, which lowercases it and replaces every other character by one underscore (`json.h` line 96, `json.cpp` line 41, the same in 7.4 and 7.5). The code writes `jref["SAS address"]`, so the key is `sas_address`.

Of the recordings read for this note, those of smartmontools 7.0 to 7.2 have `vendor`, `product`, `model_name` and `revision` instead of the `scsi_` keys, and all of 7.3 and 7.4 have the `scsi_` keys. In which version the names changed was not checked (**Assumed**: 7.3).

### Non-medium errors

`scsiprint.cpp` lines 997–1009, identical in 7.4 and 7.5: the non-medium error count and the two Hitachi counters of the same log page are written with `pout` only. `pout` adds a line to the JSON output only as text: to the array `smartctl.output` with `--json=o`, or as a key `smartctl_NNNN_u` with `--json=u` (`smartctl.cpp`, function `vjpout`, lines 1323–1367 in 7.4 and 1327–1371 in 7.5). There is no key of its own. The tool calls smartctl with `--json=c`, so the value is not in its input at all.

### Pending defects and `--xall`

`smartctl.cpp`: `--xall` is option `x` (line 342 in both), and its case sets `scsiopts.scsi_pending_defects = true` (line 763 in 7.4, 766 in 7.5). `--all` does not set it; only `-l defects` does as well (line 599 in both). `scsiprint.cpp` then reads the page only if the drive lists it as supported (`gPendDefectsLPage`, line 303; call at 3776 in 7.4, 3815 in 7.5).

## What smartctl does with RAID controllers on Linux

From `os_linux.cpp`, unless another file is named:

| Fact | 7.4 | 7.5 |
| --- | --- | --- |
| A drive behind MegaRAID gets the type `megaraid,N` and the info name `<device> [megaraid_disk_NN]`, N with two digits | 1106–1107 | 1106–1107 |
| The scan lists the drives behind MegaRAID only for SCSI hosts whose `proc_name` in `/sys/class/scsi_host` begins with `megaraid_sas` | 3027–3033 | 3019–3025 |
| Opening a device whose inquiry says `DELL    PERC`, `MegaRAID`, a product beginning with `PERC `, or the vendor `LSI` fails with "DELL or MegaRaid controller, please try adding '-d megaraid,N'". The wording is the same in both versions | 2648–2652 | 2648–2652 |
| With `--scan-open`, a device that cannot be opened keeps its entry in the scan, with that message in `devices[].open_error` (`smartctl.cpp`) | 1557 | 1561 |
| A device of the type `cciss,N` has the type `cciss` and the info name `<device> [cciss_disk_NN]` | 1545–1549 | 1545–1549 |
| `N` of `cciss,N` must be between 0 and 127 | 3591 | 3583 |
| A `cciss` device is wrapped as `sat,auto`, so a SATA drive behind it is read through SAT | 3592 | 3584 |
| smartctl checks only the `proc_name` `hpsa`, not `smartpqi`, to say that `-d cciss,N` is missing on a host in RAID mode | 3371–3409, 3485 | 3363–3401, 3477 |
| The driver `mpi3mr` does not occur in any of these files | – | – |

For a logical volume of MegaRAID, the scan therefore carries no inquiry data, only the message. The vendor and the model of the block device are in `lsblk`, which the tool reads for the enrichment of discovery; this is the structured signal that milestone M6 uses first.

smartmontools issue [313](https://github.com/smartmontools/smartmontools/issues/313), "mpi3mr-based raid controllers are not supported (e.g., PERC H965i)", is still open on 2026-10-16.

## The recordings

### Imported as fixtures

All of them were anonymized by `scripts/make_fixtures.py import` ([ADR 0026](../adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)) and are listed in [`tests/fixtures/SOURCES.md`](../../tests/fixtures/SOURCES.md). A comparison of every fixture with its source file shows changes only in the identifier fields and, where the source had replaced it by the same word as the serial number, in `smartctl.build_info` and `smartctl.platform_info`.

| Source, license | File at the commit | smartmontools | What it shows | Identifiers |
| --- | --- | --- | --- | --- |
| [libblockdev](https://github.com/storaged-project/libblockdev), LGPL-2.1-or-later (`License:` of `dist/libblockdev.spec.in`), commit `3c5433aba8c8` | `tests/smart_dumps/HGST_HUSMR3280ASS200.json` | 7.3 | Healthy SAS SSD, endurance indicator 0, **no** `scsi_grown_defect_list` | `serial_number`, `logical_unit_id` |
| same | `TOSHIBA_KPM5XMUG400G.json` | 7.3 | Healthy SAS SSD, endurance indicator and grown defect list | same |
| same | `SEAGATE_ST600MP0036.json`, `TOSHIBA_AL15SEB120NY.json` | 7.3 | Healthy SAS hard disks, with the verify counters | same |
| same | `WD4001FYYG-01SL3.json` | 7.3 | Healthy SAS hard disk, background scan log, no verify counters | same |
| [smartctl_exporter](https://github.com/prometheus-community/smartctl_exporter), Apache-2.0, commit `952076d119c8` | `testdata/HITACHI_H109060SESUN600G_9.json` | 7.3 | Healthy SAS hard disk | `serial_number`, `logical_unit_id` (replaced by the source with ascending digits) |
| same | `testdata/SEAGATE_ST373453LC_26.json` | 7.4 | **Parallel SCSI** hard disk with 260 grown defects, 1 uncorrected read error and 535 uncorrected write errors, and `smart_status.passed` true | `serial_number` |
| same | `testdata/SEAGATE_ST373453LC_27.json` | 7.4 | Healthy parallel SCSI hard disk of the same model | `serial_number` |
| [Scrutiny](https://github.com/AnalogJ/scrutiny), MIT, commit `ac2056d6c3ce` | `webapp/backend/pkg/models/testdata/smart-scsi.json` | not in the file | SAS hard disk (Seagate ST4000NM0043) with 56 grown defects and no uncorrected errors; old key names | `serial_number` |
| same | `webapp/backend/pkg/models/testdata/smart-raid.json` | 7.0 | Intel RAID 1 volume read as a SCSI device: `device_type` disk, no `smart_status`, temperature 0 | `serial_number` |
| same | `collector/pkg/detect/testdata/smartctl_scan_megaraid.json` | 7.1 | Scan with `/dev/bus/0` as `megaraid,0` and `megaraid,1`, protocol SCSI | none |
| same | `webapp/backend/pkg/models/testdata/smart-megaraid0.json`, `smart-megaraid1.json` | 7.1 | Two SATA hard disks read as `-d megaraid,N /dev/sda`, type `sat+megaraid,N`, exit status 4 | `serial_number` (replaced by the source with one repeated character, the same in both), `wwn` |
| [Telegraf](https://github.com/influxdata/telegraf), MIT, commit `2bac12a6a682` | `plugins/inputs/smartctl/testcases_scan/megaraid/response.json` | 7.1 | Scan: `/dev/sda` and `/dev/sdb` as `scsi`, `/dev/sdc` as `sat`, `/dev/bus/6` as `megaraid,8` to `megaraid,14` | none |
| same | `plugins/inputs/smartctl/testcases_device/megaraid/response.json` | 7.1 | SATA hard disk on `/dev/bus/6` read as `sat+megaraid,14` | `serial_number`, `wwn` |

The copyright lines are those of the license files, of the file header of `src/plugins/smart/smartmontools.c` for libblockdev, and of `main.go` for smartctl_exporter, which has no NOTICE file.

That `/dev/sda` and `/dev/sdb` of the Telegraf scan are logical volumes of the MegaRAID controller is **Assumed**: the scan was made without `--scan-open`, and the file says nothing about them.

### Read and not imported

| Source | Why not |
| --- | --- |
| Scrutiny `smart-scsi2.json` | Written by smartmontools 6.7, below the baseline of 7.0 ([ADR 0002](../adr/0002-supported-platforms-and-version-baseline.md)) |
| Telegraf `testcases_device/scsi/response.json` and `scsi_extended/response.json` | The source replaced vendor, product and model by made-up strings such as `XYZZZZZZ`; the values are not those of a real drive |
| smartctl_exporter `HITACHI_H109060SESUN600G_10.json`, `HP_73.4G_MAS3735NC_25.json`, libblockdev `TOSHIBA_AL15SEB18EQY.json` | Same model or same kind as an imported file; they add nothing |

### Evidence only

| Source | What it shows | Why it is not a fixture |
| --- | --- | --- |
| [Starosdev/scrutiny](https://github.com/Starosdev/scrutiny) (MIT fork of Scrutiny), `collector/pkg/detect/testdata/smartctl_info_cciss_sas.json` and `smartctl_info_cciss_sata.json`, added in commit `f5b4b11b03` with the subject "stop sharing the block device WWN across controller drives (#850)" | `--info` output of a SAS drive and of a SATA drive read as `cciss,N` behind an HP Smart Array controller | Taken from user output in issue [850](https://github.com/Starosdev/scrutiny/issues/850), whose body names a P400i and `cciss`. The repository grants MIT; the author of the output did not. No health data and no error counters |
| smartmontools issue [313](https://github.com/smartmontools/smartmontools/issues/313) | A PERC H965i on `mpi3mr`: the physical drives are not listed | Text in an issue tracker, no license |

### Not found

- smartmontools itself ships no JSON test data: the tree of `RELEASE_7_5` has no `.json` file.
- No public JSON recording of a SAS drive read as `megaraid,N`, of a MegaRAID enclosure, of a drive behind `smartpqi`, of an empty `cciss` bay, or of any `mpi3mr` host was found.
- No recording with the SAS phy log, so none with SAS addresses; the key names above are taken from the source code only.

## What follows for milestone M6

- The SAS checks of the catalog can be tested on real healthy SAS recordings, and on a real recording with grown defects of a SAS drive (version unknown) and of a parallel SCSI drive (7.4). A degraded SAS recording of a known version, and every value above the thresholds that no recording shows, are derived and marked as such ([ADR 0016](../adr/0016-test-strategy.md)).
- The missing `smart_status` of a drive without the IEC mode page must not count as a failed health verdict.
- MegaRAID can be tested on real SATA drives behind it and on real scans. SAS drives behind it, enclosures, logical volumes with `open_error`, and changed device IDs are derived.
- HPE Smart Array and `mpi3mr` rest on the source code and on synthetic fixtures. HPE stays "Experimental" ([ADR 0016](../adr/0016-test-strategy.md)); `cciss,N` is limited to N from 0 to 127 by smartctl itself.
- Q-R5 stays open for recordings from users; the call for recordings arrives at the end of M6.

## Addition 2026-10-16: the maintainer's TrueNAS host

Recorded on 2026-10-16 through the read-only wrapper of the host `truenas` of the maintainer: smartmontools 7.4 on Linux 6.12, three NetApp X371 SAS SSDs behind an LSI SAS2308 HBA, whose SCSI host has the `proc_name` `mpt2sas`, and one Samsung SATA SSD on the AHCI controller of the board. The anonymized recording is `tests/fixtures/smartctl/hba/maintainer-truenas/`; the raw output stays outside the repository ([ADR 0016](../adr/0016-test-strategy.md)). Everything here is **Verified** on that host or in the source code named.

- **Q-R6 is answered for these drives:** the WWN that `lsblk` shows for each SAS SSD is its `logical_unit_id`, digit for digit, and the anonymizer gives both the same placeholder ([ADR 0026](../adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)). The SAS addresses differ from the logical unit id.
- **The SAS addresses are in the output of `--xall`** under `scsi_sas_port_N.phy_M.sas_address` and `attached_sas_address`, as the source code says. The second port of each drive is attached to nothing and has the attached address `0x0`.
- **`smart_support.enabled` of a SCSI drive** says whether the informational exceptions are switched on (`scsiprint.cpp` line 3181 in 7.4, 3220 in 7.5), and `smartctl -s on` switches them on (line 3598 in 7.4, 3637 in 7.5). With them off, the drive does not report a failing health. One public recording, the WD4001FYYG of libblockdev, has them off.
- **The self-test log of a SCSI drive** lists the most recent test first, as `scsi_self_test_0` (`scsiprint.cpp` line 1137). Its `result.value` is 0 for a test completed without error, 1 and 2 for aborted tests, 3 to 7 for an error or a failed segment, for which smartctl sets its own failure bits, and 15 for a test in progress (table at line 1066, cases from line 1161; the same in 7.4 and 7.5).
- **A SCSI device without the informational exceptions mode page** gets `smart_support.available` false, written where the mode page cannot be read (`scsiprint.cpp` line 3167 in 7.4, 3206 in 7.5). A missing `temperature.current` is a value of 255, which smartctl leaves out (line 407); a 0 is a value the device reported.
- **The start-stop cycles** are `scsi_start_stop_cycle_counter.accumulated_start_stop_cycles` (line 548 in both).

These drives are SAS and reached through an HBA in IT mode. They are no evidence for MegaRAID or any other RAID controller.

## Addition 2026-10-16, later: the TrueNAS host recorded with the call of the tool

The first recording of the TrueNAS host was made with `smartctl -x --json=c -n standby -d TYPE DEVICE` for every drive. The tool passes `--nocheck=standby` only for ATA types, and for a SCSI drive `-n standby` makes smartctl check the power condition first and end without data if the drive is in standby (`scsiprint.cpp` lines 3514–3578 in 7.5), so that recording did not show what the tool reads. The wrapper of the maintainer was changed to make the call of the tool: `smartctl --json=c --xall --device=TYPE DEVICE`, with `--nocheck=standby` for `ata`, `sat` and `sat+…` only.

The host was recorded again at 14:52 UTC; this recording replaces the first one in `tests/fixtures/smartctl/hba/maintainer-truenas/`. The SAS SSDs answer as before: no grown defects, no uncorrected errors, health passed, endurance indicator 0 to 5 %, the WWN in `lsblk` equal to the logical unit id. Between the two recordings the power-on hours rose by 3 and the temperature of one drive by 1 °C. Replayed through `scan`, `check --dry-run` and the renderer, the host shows four monitored drives without findings.

## Addition 2026-10-16: how smartctl treats a MegaRAID logical volume in the scan and when it is read

From the source code of smartmontools 7.4 and 7.5, **Verified**; no recording shows it (Q-R1):

- Without `-d`, the scan creates a device for every `/dev/sdX` without a type (`autodetect_smart_device`; the scan without types, `os_linux.cpp` line 3109 in 7.4 and 3101 in 7.5, and the call at line 2973 in 7.4 and 2965 in 7.5). `--scan-open` opens it with `autodetect_open`, which reads the inquiry data and refuses a MegaRAID controller with the message of line 2652, so the entry of a logical volume carries that message in `open_error` and keeps the type `scsi`.
- When a type is given, as the tool does with `--device=scsi`, `autodetect_open` returns before that check (`os_linux.cpp` lines 2600–2605 in both versions). The drive output of a logical volume then has its inquiry data and no message.
- smartctl takes these inquiry data for a MegaRAID controller: the vendor `DELL` with a product beginning with `PERC`, the vendor `MegaRAID`, a product beginning with `PERC `, and a vendor field of `LSI` followed by a zero byte (lines 2648–2650).

[ADR 0028](../adr/0028-logical-volumes-and-enclosures.md) builds on these facts.

## Addition 2026-10-16, evening: the SCSI hosts of the maintainer's hosts, and what is known about `mpi3mr`

The SCSI hosts were recorded on 2026-10-16. On `truenas`, `pve5`, `pve6` and `pve7` at 20:04 UTC through the command `hosts` of the read-only wrapper, which prints every SCSI host with its `proc_name` from `/sys/class/scsi_host/hostN/proc_name`, and then the storage controllers that `lspci` lists. On the standalone host `pve-test` (`pve1`, Proxmox VE kernel 7.0.6-2-pve) at about 20:40 UTC, from the same files and the target of each link in `/sys/class/scsi_host`. The output holds no serial number. The table is **Verified** on these hosts.

| Host | SCSI hosts and drivers | Storage controllers in `lspci` |
| --- | --- | --- |
| `truenas` (TrueNAS SCALE, kernel 6.12.33-production+truenas) | `host0` `mpt2sas`; `host1` to `host6` `ahci`; `host7` `ahciem` | Intel Cannon Lake PCH SATA AHCI controller `[8086:a352]`; Broadcom / LSI SAS2308 PCI-Express Fusion-MPT SAS-2 `[1000:0087]` |
| `pve5` | `host0`, `host1` `ahci` | Intel Celeron/Pentium Silver SATA controller `[8086:31e3]` |
| `pve6` | `host0`, `host1` `ahci` | Intel 200 Series PCH SATA controller in AHCI mode `[8086:a282]`; SanDisk / WD NVMe SSD `[15b7:5002]` |
| `pve7` | `host0` to `host5` `ahci` | Intel 5 Series/3400 Series 6 port SATA AHCI controller `[8086:3b22]`; two Samsung SM961/PM961 NVMe SSDs `[144d:a804]` |
| `pve-test` (kernel 7.0.6-2-pve) | `host0`, `host1` `ahci`; `host2` `usb-storage` | Not recorded |

- **One SCSI host per AHCI port.** The number of `ahci` hosts follows the ports of the controller, not the drives attached. On `pve-test` they are `ata1` and `ata2` of the controller at `0000:00:13.0`.
- **The entries of `/sys/class/scsi_host` are links** into `/sys/devices`, for example `host0` to `../../devices/pci0000:00/0000:00:13.0/ata1/host0/scsi_host/host0`.
- **A USB storage device is a SCSI host of its own**, with the driver `usb-storage`: on `pve-test` the virtual drive of the KVM-over-IP device, below `usb1/1-4/1-4.1/1-4.1.1`.
- **`ahciem` is a SCSI host of its own** next to the `ahci` hosts of the TrueNAS host, seen only on the TrueNAS SCALE kernel; `pve-test` with kernel 7.0.6 has none. It is taken for the enclosure management of AHCI, but where it comes from was not checked in kernel source: a web search found no `proc_name` of that name in the Linux source, only FreeBSD documents AHCI enclosure management under it (**Assumed**).
- **The HBA is one SCSI host with `mpt2sas`**, whose drives smartctl reads directly (the addition on the TrueNAS host above).
- **NVMe controllers have no SCSI host.** The NVMe drives of `pve6` and `pve7` appear only in `lspci`.

No host shows an `mpi3mr` controller, and no recording of one exists. What is known about it, checked on 2026-10-16:

- **Issue 313 covers the RAID personality only** (**Verified** in the issue): a PERC H965i Front with one RAID 0 virtual drive, titled "Physical drives are not shown for raid controller PERC H965i Front with driver mpi3mr". Dell writes there that the "PERC 12 H965 does not block SmartCTL, but the tool has to use passthrough commands to get to the devices behind the perc".
- **Broadcom 9600-series cards run `mpi3mr` in an "Enhanced HBA Personality" as well**, in which the drives are exposed to the system (**Reported**, `dmesg` of a 9600-24i in a TrueNAS forum thread). Whether smartctl reads the drives in that personality is not recorded anywhere (Q-R7). An `mpi3mr` host in HBA personality may therefore be reported although its drives are monitored.

[ADR 0030](../adr/0030-controllers-whose-drives-cannot-be-queried.md) builds on these facts: none of the recorded drivers is reported as a controller whose drives cannot be queried, and the text about `mpi3mr` names the drives in RAID mode only. The tests use sysfs trees built from the TrueNAS host, from `pve7` and from `pve-test` (`tests/unit/hosts.py`).

## Sources

- smartmontools at `RELEASE_7_4` and `RELEASE_7_5`: <https://github.com/smartmontools/smartmontools/tree/RELEASE_7_5/smartmontools>
- smartmontools issue 313: <https://github.com/smartmontools/smartmontools/issues/313>
- TrueNAS forum, "9600-24i mpi3mr error on passthrough" (Enhanced HBA Personality): <https://forums.truenas.com/t/9600-24i-mpi3mr-error-on-passthrough/42408>
- libblockdev: <https://github.com/storaged-project/libblockdev/tree/3c5433aba8c87b83a590d9363bf0fc71c205e08a/tests/smart_dumps>
- smartctl_exporter: <https://github.com/prometheus-community/smartctl_exporter/tree/952076d119c8a17abdb075871348e072263de822/testdata>
- Scrutiny: <https://github.com/AnalogJ/scrutiny/tree/ac2056d6c3cef4a8dd6fe3e0b8c002d9595da75f>
- Telegraf: <https://github.com/influxdata/telegraf/tree/2bac12a6a682e02f2ef42a43d40a259083892212/plugins/inputs/smartctl>
- Starosdev/scrutiny issue 850: <https://github.com/Starosdev/scrutiny/issues/850>
