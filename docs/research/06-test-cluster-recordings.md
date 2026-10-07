# Research 06: Recordings from the test cluster

What the first recordings from the test cluster show about the drive data, the wear values and the notification configuration.
They were taken on 2026-10-05 on the three nodes `pve5`, `pve6` and `pve7`: first `pve7` by hand, together with two configurations of the notification matchers, then all three nodes with [`scripts/collect-node-data.sh`](../../scripts/collect-node-data.sh).
The recording by hand is used only for its two matcher configurations. Everything else comes from the recordings of the script, which are complete and alike on all three nodes.
Everything in this note is **Verified** on these recordings, unless it is marked otherwise.

The raw archives contain real serial numbers and WWNs and are not part of the repository ([ADR 0016](../adr/0016-test-strategy.md)). The anonymized fixtures made from the recordings of the script are in `tests/fixtures/smartctl/direct/` ([ADR 0023](../adr/0023-anonymization-of-recordings.md)).

## Versions

All three nodes: Proxmox VE 9.2.21 (`pve-manager` 9.2.21, kernel 7.0.14-19-pve), smartmontools 7.5 from the Proxmox VE package `7.5-pve2` (as listed by `pveversion -v`), PVE SMART Alert 0.1.0.

Proxmox VE 9.2 ships smartmontools 7.5. The notes 02 to 04 and the records [ADR 0002](../adr/0002-supported-platforms-and-version-baseline.md) and [ADR 0004](../adr/0004-smartctl-json-as-data-source.md) state 7.4, which was observed on Proxmox VE 9.1. The vendor-neutral JSON values of 7.5 are therefore available on the current release line, and 7.4 remains the version to support for older 9.x hosts. This is the revisit condition named in [ADR 0010](../adr/0010-health-evaluation-and-default-thresholds.md); for the wear value it is handled by [ADR 0021](../adr/0021-wear-value-source.md), for the spare value in milestone M3.

## Drives

| Node | Model | smartctl type | Class | LVM volume group | Wear, web interface | `endurance_used` |
| --- | --- | --- | --- | --- | --- | --- |
| pve5 | Fanxiang S301 256GB | `sat` | SATA SSD | `pve` (partition 3) | 0 % | 44 % |
| pve5 | USB mass storage (virtual drive of a KVM-over-IP device) | – | USB | none (exFAT) | N/A | not in the scan |
| pve6 | WDC PC SN720 SDAPNTW-512G-1016 | `nvme` | NVMe | `pve` (partition 3) | 0 % | 0 % |
| pve6 | Samsung SSD 750 EVO 500GB | `sat` | SATA SSD | `vg_data` (whole disk as physical volume, no partition table) | 35 % | 35 % |
| pve7 | Samsung SSD 850 EVO 250GB | `sat` | SATA SSD | `pve` (partition 3) | 12 % | 12 % |
| pve7 | Samsung MZVLW256HEHP (PM961) | `nvme` | NVMe | `pm961-b` (whole disk) | 2 % | 2 % |
| pve7 | Samsung MZVLW256HEHP (PM961) | `nvme` | NVMe | `pm961-a` (whole disk) | 19 % | 19 % |

The models are those that smartctl reports. The disk list of the web interface (`/nodes/NODE/disks/list`) writes the models of the SATA drives and of the USB device with underscores instead of spaces, for example `Samsung_SSD_850_EVO_250GB`; for the NVMe drives it shows the same model as smartctl.

None of the nodes uses ZFS. Every LVM volume group carries an LVM-thin pool.

On the three nodes the volume group of a drive can be read from `lsblk` alone. `lsblk` shows each physical volume, a whole disk or a partition, with the file system type `LVM2_member`, and the device-mapper devices that use it as its children, with the type `lvm`. The name of such a device starts with the name of the volume group, followed by a single dash; a dash inside the name of a volume group or a logical volume is doubled, as in `pm961--a-data_tmeta` for the volume group `pm961-a`. Read up to the first single dash, with each doubled dash reduced to one, the names give for every physical volume of the three nodes the volume group that `pvs` reports.

## Device scan

- `smartctl --scan-open --json=c` returns `devices`, an array of objects with `name`, `info_name`, `type` and `protocol`, for example `{"name": "/dev/sda", "info_name": "/dev/sda [SAT]", "type": "sat", "protocol": "ATA"}`. NVMe drives appear as the controller device `/dev/nvmeN` with type `nvme`.
- Every physical drive appears exactly once. Partitions, LVM volumes and namespaces do not appear.
- The USB device on `pve5` is the virtual drive of a KVM-over-IP device, used to mount ISO images. It is listed by the web interface (`pvesh get /nodes/pve5/disks/list`, type `usb`, health `UNKNOWN`) but does not appear in the scan, so discovery never sees it. It is ignored.
- No device that could not be opened was seen, so the form of such an entry is still open (Q-S1).

## Drive output of `smartctl -x --json=c`

- All six drives answered with exit status 0 and no messages, with and without `-d TYPE`.
- ATA drives have `ata_smart_attributes`, `ata_sct_status`, `ata_sct_temperature_history`, `ata_smart_self_test_log` and `sata_phy_event_counters`.
- NVMe drives have `nvme_smart_health_information_log`, `nvme_self_test_log`, `nvme_error_information_log` and `nvme_composite_temperature_threshold`. The object `temperature` carries the warning and critical limits of the drive as `op_limit_max` and `critical_limit_max`.
- All six drives have the 7.5 values `endurance_used.current_percent` and `spare_available.current_percent`; most also have `spare_available.threshold_percent`.
- The ATA Device Statistics log appears as `ata_device_statistics.pages[].table[]` with `name` and `value`. Only the Fanxiang drive has it. The two Samsung SATA drives have no device statistics; smartmontools 7.5 nevertheless reports `endurance_used` for them, with the same value as their attribute 177. How smartmontools derives the value when the log is missing is **Assumed** to be its drive database and has not been checked in its source code.

## Wear values

The web interface takes the wear of an ATA drive from the first attribute whose name is on a fixed list, with `Wear_Leveling_Count` on it ([Research 02](02-builtin-smart-handling.md), `PVE::Diskmanage`). The API field `wearout` of `/nodes/NODE/disks/list` is the remaining life, 100 meaning new; the web interface shows it as used, `100 - wearout`.

The Fanxiang S301 reports three different values:

| Source | Value | Wear |
| --- | --- | --- |
| Attribute 177 `Wear_Leveling_Count`, normalized | 100 | 0 %, shown by the web interface |
| Attribute 231, normalized (not named in the drive database of smartmontools, so not on the list of the web interface) | 82 | 18 % |
| ATA Device Statistics, "Percentage Used Endurance Indicator" | 44 | 44 % |
| smartmontools 7.5 `endurance_used.current_percent` | 44 | 44 % |

The drive has 7,109 power-on hours. Attribute 241 has the raw value 63,513, in a unit that is not known for this model. The raw value of attribute 177 is 5,061,988. Which value is true cannot be proven from the outside. The device statistics are the value defined by the ATA standard, and smartmontools reports the same number. [ADR 0021](../adr/0021-wear-value-source.md) decides which source the tool uses.

For the other five drives all sources that exist agree with the web interface.

## Quirks seen

- Fanxiang S301: attribute 187 `Reported_Uncorrect` has the worst value 0 with a raw value of 0 and a threshold of 0. A check must not read the worst value as a failure.
- Fanxiang S301: the temperature limits are reported as -127 and 127, which are placeholders and not limits.
- Fanxiang S301: attribute 194 has the raw value 214,750,527,538, a packed value. The current temperature has to come from `temperature.current` (50 °C), not from the raw attribute value.

## Notification configuration

Read with `pvesh get /cluster/notifications/matchers --output-format json` and `.../targets`:

- A matcher has `name`, `mode`, `target` (list), `match-field` (list), `match-severity` (list), `origin`, and optionally `comment` and `disable`.
- `disable` appears on matchers as well as on targets, as `"disable": 1`. It is absent when the matcher or target is enabled.
- `regex:` is the prefix of a regex rule in `match-field`, as in `regex:type=^pve-smart-alert$`, and `exact:` of an exact rule. One `exact:` rule can list several values separated by commas: `exact:type=vzdump,system-mail`.
- One string of `match-severity` can list several severities separated by commas: `info,notice,warning,error`.
- `origin` was seen as `modified-builtin` and `user-created`. That an unchanged built-in matcher has `builtin` is **Assumed**. No recording contains one, because the default matcher of the test cluster is modified in all of them.
- `invert-match` and `match-calendar` were not configured on the test cluster and remain unobserved.

Three matcher configurations were recorded. They are the fixtures of the routing check in milestone M2 and cover the three cases of its acceptance step 5 ([ROADMAP.md](../../ROADMAP.md)).

| Configuration | Recorded on | `default-matcher` | Matcher `pve-smart-alert` |
| --- | --- | --- | --- |
| A: as left by milestone M1 | `pve7`, by hand | `exact:type=vzdump,system-mail` | `regex:type=^pve-smart-alert$`, severities `warning,error` |
| B | `pve7`, by hand | `exact:type=vzdump` | As in A, but disabled |
| C: in use since 2026-10-05 | All three nodes, by the script | As in A | As in A, with the severities `info,notice,warning,error` |

All matchers have the mode `all` and the same single target, an SMTP target that is enabled. The two disabled targets, `mail-to-root` and a second SMTP target, are used by no matcher, so no recording shows a matcher whose only target is disabled.
