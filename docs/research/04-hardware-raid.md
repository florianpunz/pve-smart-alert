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

Read in `smartctl.8.in`, `os_linux.cpp`, `dev_interface.cpp`, `scsiata.cpp`, `scsiprint.cpp`, `ataprint.cpp` and `dev_jmb39x_raid.cpp` of the tags `RELEASE_7_4` and `RELEASE_7_5` of smartmontools, for [ADR 0034](../adr/0034-manual-entries-of-other-pass-through-types.md). Line numbers are those of 7.5 unless 7.4 is named. It corrects the summary table above in one row and settles what the table left as **Assumed**.

- **Which controllers the scan lists.** `scan_smart_devices` (lines 3074 to 3140) lists the block devices `/dev/hd*` and `/dev/sd*`, NVMe devices, and the drives of two controller families: MegaRAID through `get_dev_megasas` and SSSRAID through `get_dev_sssraid` (line 3131; 7.4 line 3139). The latter reads the `proc_name` of every SCSI host below `/sys/class/scsi_host`, and for each host with the driver `sssraid` it lists every SATA, SAS or NVMe drive the controller reports as `/dev/bsg/sssraidN` with the type `sssraid,E,S` (lines 3039 to 3072 and 3319 to 3347), without the `sat,auto` of a read, so with protocol SCSI and an `info_name` without ` [SAT]` or ` [SCSI]`. The row "Found by `smartctl --scan`: Unknown" of SSSRAID above is therefore "Yes", and "No" for HPE, Adaptec, Areca, 3ware and HighPoint is **Verified** in the source, no longer **Assumed**.
- **How the scan lists a logical volume of these controllers.** With `--scan-open`, a block device whose inquiry data begin with `3ware` or `AMCC` gets the `open_error` "AMCC/3ware controller, please try adding '-d 3ware,N'" (lines 2639 to 2645, the same in 7.4), as one of MegaRAID gets the one that asks for `-d megaraid,N`. A block device of an `hpsa` controller in RAID mode is left out of the scan, because its autodetection asks for `-d cciss,N` (`is_hpsa_in_raid_mode`, lines 3475 to 3477; 7.4 lines 3484 to 3485) and the scan skips a device that cannot be detected (lines 2964 to 2967); one of `smartpqi` is listed. The logical volume of Adaptec, Areca, HighPoint and SSSRAID is listed as an ordinary `/dev/sdX` with the type `scsi` or `sat`. **Verified** in the source; what such a volume answers when it is read is not recorded.
- **What smartctl writes into the device fields of a drive behind a controller.** The constructors of the devices write the `info_name` `[aacraid_disk_HH_LL_ID]` (line 865), `[3ware_disk_NN]` (line 1595), `[areca_disk#NN_enc#EE]` (lines 2089 and 2154), `[hpt_disk_L/M/N]` (line 2363), `[sssraid_disk_EE_SS]` (line 1411), `[megaraid_disk_NN]` (line 1106) and `[cciss_disk_NN]` (line 1549) after the node. The types `cciss`, `aacraid` and `sssraid` are opened through an implicit `sat,auto` (lines 3584, 3596 and 3603), which decides by the inquiry data: for a SATA drive it writes the type `sat` and adds ` [SAT]` to the `info_name`, for a SAS drive it keeps the type of the device class and adds ` [SCSI]` (`scsiata.cpp` lines 545 to 547). The type of the device class is `cciss`, `aacraid,H,L,ID` or `sssraid,E,S`; `3ware`, `areca` and `hpt` write the bare names `3ware`, `areca` and `hpt` (lines 1591, 2084, 2149 and 2359). The type in the output is therefore not the type of the call, except for a SAS drive behind Adaptec or SSSRAID. **Verified** in the source.
- **The prefixes before a controller type.** smartctl takes a type that starts with `sat` followed by `,` or `+`, or with `scsi+`, splits it at the first `+`, and refuses the result unless the device of the rest is a SCSI device (`dev_interface.cpp` lines 440 to 457). So `sat,auto+aacraid,0,0,2`, `sat,12+megaraid,2`, `sat,16+cciss,0` and `sat,auto+sssraid,0,1` are valid, and the prefixes before `3ware`, `areca` and `hpt`, whose devices are ATA devices, are refused with "Device type … is not SCSI". The manual names `scsi+cciss,N` and `scsi+aacraid,H,L,ID` to switch the implicit SAT off. **Verified** in the source.
- **The JMicron types write to the RAID volume.** smartctl(8) of 7.4 and 7.5 warns for `jmb39x` and `jms56x` that the commands "are issued via READ/WRITE commands to a LBA of the RAID volume" and that "Original sector data is not written back if smartctl is aborted with a signal". The variant `jmb39x-q2` is new in 7.5; the 7.4 manual has `jmb39x[-q],N`. smartctl takes these types at the start of a type (`dev_interface.cpp` lines 468 to 480); after `sat+` or `scsi+` they are refused, because their device is not a SCSI device. **Verified** in the manual and the source.
- **The power condition of a SCSI drive in standby is named in words.** When `-n standby` ends the call of a SCSI drive, smartctl writes "Device is in NAME mode, exit(N)" with the names `LOW POWER`, `STANDBY BY TIMER`, `STANDBY BY COMMAND`, `STANDBY_Y BY TIMER` and `STANDBY_Y BY COMMAND` (`scsiprint.cpp` lines 3537 to 3577; 7.4 lines 3498 to 3537); a drive that does not report its power condition is read as active. An ATA drive names one word, such as `STANDBY` (`ataprint.cpp` line 3448). **Verified** in the source.
- **smartctl creates device nodes for some controllers.** For `aacraid` it creates `/dev/aacH` with `mknod` when it is missing (line 908); for `3ware` it creates the nodes `/dev/twaN`, `/dev/twlN` or `/dev/tweN`, and unlinks and recreates one whose numbers are wrong (lines 1683 to 1716; the manual says the same); for MegaRAID it creates its ioctl node `/dev/megaraid_sas_ioctl_node` when it is missing and `/proc/devices` lists the driver, in the scan (line 2997) and on a read of `megaraid,N` (line 1184), and `/dev/megadev0` of an old controller on a read (line 1191). **Verified** in the source.

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
