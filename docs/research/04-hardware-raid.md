# Research 04: Drives behind hardware RAID controllers

- Research date: 2026-10-03
- Applies to: smartmontools 7.4 on Linux (Proxmox VE 9).
- Used by: [ADR 0005](../adr/0005-drive-discovery-and-identity.md), [ADR 0016](../adr/0016-test-strategy.md), [ADR 0017](../adr/0017-scope-of-version-1.md)

## Summary

| Controller family | Linux driver | smartctl option | Found by `smartctl --scan` | Plan for PVE SMART Alert |
| --- | --- | --- | --- | --- |
| Broadcom/LSI MegaRAID, Dell PERC up to generation 11, and other rebrands | `megaraid_sas` | `-d megaraid,N` | Yes, as `/dev/bus/<host> -d megaraid,<N>` | Automatic in version 1 |
| HPE Smart Array | `hpsa`, `smartpqi` (legacy: `cciss`) | `-d cciss,N` | No | Probing, experimental in version 1 |
| Adaptec / Microchip | `aacraid` | `-d aacraid,H,L,ID` | No | Manual device entries |
| Areca | `arcmsr` | `-d areca,N` or `areca,N/E` | No | Manual device entries |
| 3ware | `3w-*` | `-d 3ware,N` | No | Manual device entries |
| HighPoint RocketRAID | – | `-d hpt,L/M/N` | No | Manual device entries |
| SSSRAID | – | `-d sssraid,E,S` (new in 7.4) | Unknown | Manual device entries |
| Broadcom MegaRAID 96xx, Dell PERC 12 (H965i) | `mpi3mr` | none | No | Not possible. Upstream limitation |
| Any controller in HBA / IT mode | – | none needed | Yes, as plain SATA/SAS devices | Automatic |

"Found by scan: No" is **Assumed** for all rows except MegaRAID and `mpi3mr`. It rests on the manual page, which documents these types only as explicit `-d` arguments, and on reports of people configuring them by hand.

## MegaRAID

**Verified** in issue reports that quote real output:

```text
# smartctl --scan
/dev/sda -d scsi # /dev/sda, SCSI device
/dev/bus/0 -d megaraid,0 # /dev/bus/0 [megaraid_disk_00]
/dev/bus/0 -d megaraid,1 # /dev/bus/0 [megaraid_disk_01]
```

```json
{"devices": [
  {"name": "/dev/sda", "type": "scsi", "protocol": "SCSI"},
  {"name": "/dev/bus/2", "info_name": "/dev/bus/2 [megaraid_disk_00]", "type": "megaraid,0", "protocol": "SCSI"}
]}
```

Facts and pitfalls:

- The device name is `/dev/bus/<SCSI host number>`. It is not a real device node. It is only meaningful together with `-d megaraid,N`. Tools that drop the `-d` part fail (Telegraf issues 15095 and 15255, smartctl_exporter issue 26).
- `N` is the controller's device ID, not the slot. It can change when a drive is replaced. **Reported** (Proxmox forum, 2026): after replacing the disk in slot 2 the new disk answered as `megaraid,5`. The device ID must not be used as identity.
- The logical volume (`/dev/sda` above) is listed as a SCSI device. It has no SMART data. It must be recognized and skipped, not reported as a drive without SMART.
- The scan also returns devices on the controller that are not disks or that do not answer SMART commands. **Reported**: smartd mailed daily about `megaraid_disk_11`, which was the enclosure.
- SATA drives behind the controller need SCSI-to-ATA translation. `--scan-open` is expected to report them as `sat+megaraid,N`. **Assumed**; the syntax is mentioned in forum posts, real scan output is needed.
- Some controller and firmware combinations cannot return the SMART status of SATA drives: "SMART Status not supported: Incomplete response, ATA output registers missing". Attributes can still be read (smartmontools issue 264, MegaRAID SAS 2008 with 7.4). A missing health verdict must therefore not block the evaluation of attributes.
- In JBOD mode a drive can appear twice, as `/dev/sdX` and as `megaraid,N`. De-duplication by serial number is required.
- Mapping a device ID to enclosure and slot needs the vendor tool (`storcli`, `perccli`), which is not installed by default.
- NVMe drives behind a tri-mode controller: no information found. **Open question.**

## HPE Smart Array

**Verified** in `smartctl(8)`:

- `-d cciss,N` addresses physical drive `N` on the controller.
- With the old `cciss` driver the device is `/dev/cciss/c0d0`. With `hpsa` (and, **Reported**, `smartpqi`) it is a SCSI generic node such as `/dev/sg2`, or a logical drive such as `/dev/sda`.

Not covered by the scan (**Assumed**). smartctl_exporter has had an open request for `-d cciss,N` support for years, and Proxmox forum users pass the option by hand.

A tool therefore has to probe: detect that an `hpsa` or `smartpqi` host exists, pick a device node of that controller, and try `cciss,0`, `cciss,1`, ... until the controller stops answering.
Open points: the valid range of `N`, whether gaps in the numbering occur, which device node is the right one with `smartpqi`, and how smartctl reports an empty bay. None of this can be answered without recorded output from real hardware.

## `mpi3mr` controllers

**Verified** in smartmontools issue 313 (open, with a draft patch): physical drives behind controllers that use the `mpi3mr` driver (Dell PERC H965i, Broadcom MegaRAID 96xx) are not listed by `smartctl --scan` and cannot be queried. Only the virtual drive appears. No workaround exists inside smartctl.

PVE SMART Alert cannot cover these controllers as long as it relies on smartctl. It should detect the driver and say so clearly in `pve-smart-alert doctor` and `pve-smart-alert scan` instead of silently monitoring nothing.

## What "reliable detection" means in practice

1. Use `smartctl --scan-open --json` as the primary source, and always keep name and type together.
2. Add probing for controller families the scan does not cover, driven by the kernel driver that is loaded.
3. Accept manual device entries as a last resort.
4. Decide what a device is from the smartctl output, not from its name: skip logical volumes, enclosures and anything else that is not a disk with SMART data, without raising an alert.
5. Identify drives by model and serial number. Treat the device ID and the device node as changeable attributes.
6. De-duplicate by serial number.
7. Tell the administrator what was found and what was skipped, and why.

## Testing without hardware

No RAID controller is available to the project. The plan in [ADR 0016](../adr/0016-test-strategy.md):

- Recorded smartctl output as fixtures, including scan output, for each controller family.
- A fake `smartctl` executable that replays fixtures, so that discovery, collection and evaluation run end to end in CI.
- A `pve-smart-alert dump-fixture` command that records and anonymizes the output on a real system, so that users with such hardware can contribute fixtures through an issue.
- Controller support is labeled by evidence: "verified on hardware", "verified by fixtures", "experimental".

Public sources of recorded output that can seed the fixture set: the Scrutiny test data (MIT) and outputs quoted in public issue trackers. License and anonymization must be checked for each file.

## Addition of 2026-10-17: the other controller types in the source of 7.4 and 7.5

Read in `smartctl.8.in`, `os_linux.cpp`, `dev_interface.cpp` and `dev_jmb39x_raid.cpp` of the tags `RELEASE_7_4` and `RELEASE_7_5` of smartmontools, for [ADR 0034](../adr/0034-manual-entries-of-other-pass-through-types.md). It corrects the summary table above in one row and adds what the table left open.

- **SSSRAID is listed by the scan.** `scan_smart_devices` calls `get_dev_sssraid` next to `get_dev_megasas` (7.5 line 3131, 7.4 line 3139). It reads the `proc_name` of every SCSI host below `/sys/class/scsi_host`, and for each host with the driver `sssraid` it lists every drive the controller reports as `/dev/bsg/sssraidN` with the type `sssraid,E,S` (7.5 lines 3039 to 3069 and 3319 to 3347). The row "Found by `smartctl --scan`: Unknown" above is therefore "Yes". **Verified** in the source; no recording exists.
- **The `info_name` of a drive behind each controller**, as the constructors of the devices write it (7.5): `[aacraid_disk_HH_LL_ID]` (line 865), `[3ware_disk_NN]` (line 1595), `[areca_disk#NN_enc#EE]` (lines 2089 and 2154), `[hpt_disk_L/M/N]` (line 2363), `[sssraid_disk_EE_SS]` (line 1411), next to `[megaraid_disk_NN]` (line 1106) and `[cciss_disk_NN]` (line 1549). **Verified** in the source.
- **The prefixes before a controller type.** smartctl takes a type that starts with `sat` followed by `,` or `+` and splits it at the first `+`, so `sat,auto+aacraid,0,0,2` and `sat,12+megaraid,2` are valid forms (`dev_interface.cpp` of 7.5, lines 440 to 457); the manual names `scsi+cciss,N` and `scsi+aacraid,H,L,ID` to switch the implicit SAT off. **Verified** in the source.
- **The JMicron types write to the RAID volume.** smartctl(8) of 7.4 and 7.5 warns for `jmb39x` and `jms56x` that the commands "are issued via READ/WRITE commands to a LBA of the RAID volume" and that "Original sector data is not written back if smartctl is aborted with a signal". The variant `jmb39x-q2` is new in 7.5; the 7.4 manual has `jmb39x[-q],N`. smartctl dispatches on these prefixes at the start of a type or after a `+` (`dev_interface.cpp` of 7.5, lines 468 to 480). **Verified** in the manual and the source.
- **smartctl creates device nodes for some controllers.** For `aacraid` it creates `/dev/aacH` with `mknod` when it is missing (7.5 line 908); for `3ware` it creates the nodes `/dev/twaN`, `/dev/twlN` or `/dev/tweN`, and unlinks and recreates one whose numbers are wrong (7.5 lines 1683 to 1716; the manual says the same); for MegaRAID it creates its ioctl node, also during the scan (7.5 lines 1184, 1191 and 2997). **Verified** in the source.

## Sources

- `smartctl(8)`, smartmontools 7.4, option `-d TYPE`: <https://manpages.debian.org/trixie/smartmontools/smartctl.8.en.html>
- Telegraf issue 15095 (scan output with MegaRAID): <https://github.com/influxdata/telegraf/issues/15095>
- Telegraf issue 15255 (JSON scan output with MegaRAID): <https://github.com/influxdata/telegraf/issues/15255>
- smartmontools issue 313 (`mpi3mr` not supported): <https://github.com/smartmontools/smartmontools/issues/313>
- smartmontools issue 264 (SMART status through MegaRAID SAT): <https://github.com/smartmontools/smartmontools/issues/264>
- smartctl_exporter issue 26 (`-d cciss,N` not supported by the exporter): <https://github.com/prometheus-community/smartctl_exporter/issues/26>
- Forum "can not get disk smart information" (device ID changed after replacement): <https://forum.proxmox.com/threads/can-not-get-disk-smart-information.181407/>
- Forum "SMART errors with Megaraid" (enclosure device reported by smartd): <https://forum.proxmox.com/threads/smart-errors-with-megaraid.54722/>
- Forum "Disk smart status no longer working" (`-d cciss,N`, `-d megaraid,N` by hand): <https://forum.proxmox.com/threads/disk-smart-status-no-longer-working.82748/>
