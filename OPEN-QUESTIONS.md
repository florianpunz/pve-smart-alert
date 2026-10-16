# Open questions

Everything that could not be settled during planning.
Each entry says why it matters, what is assumed until it is answered, and when it gets answered.
Answered entries are removed from this file; the answer goes into the document it affects, and into a new decision record if it changes a decision.

## For the maintainer

None at the moment.

## Notification route

The acceptance run of milestone M1 answered Q-N1 to Q-N3 and Q-N7, and the routing check of [ADR 0020](docs/adr/0020-routing-check.md) answered Q-N8, whether the tool can tell that no matcher matched; the answers are in [ARCHITECTURE.md](ARCHITECTURE.md) section 10. Q-N4, how long a slow target blocks the call, was answered on `pve1` on 2026-10-13, with the answer in [ARCHITECTURE.md](ARCHITECTURE.md) section 10. Q-N5 needs a degraded cluster and is answered in milestone M5; Q-N6 needs the Proxmox developers. Q-N9, whether `/etc/pve/corosync.conf` names the cluster, was answered on the test cluster on 2026-10-12; the answer is in [ARCHITECTURE.md](ARCHITECTURE.md) section 10. Q-N10, how a matcher selects one drive behind a RAID controller, was decided by the maintainer on 2026-10-16: a new field `device-id`, built next ([ROADMAP.md](ROADMAP.md), M6).

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-N5 | What happens to the bridge when pmxcfs has no quorum or is not running? | Behavior in a degraded cluster | Without pmxcfs the bridge fails and the fallback is used. Without quorum, `/etc/pve/corosync.conf` stays readable, so notifications keep the cluster name |
| Q-N6 | Do the Proxmox developers plan a supported interface for custom notifications, or the "notification registry" mentioned in their source code? | Would replace the bridge with something stable | Unknown. To be asked on the Proxmox forum or development list once M1 has produced concrete findings |

## smartctl output and discovery

Answered in milestone M2 with recordings from the test cluster ([Research 06](docs/research/06-test-cluster-recordings.md)), made with smartmontools 7.5, which Proxmox VE 9.2 ships, and with the source of smartmontools 7.4 and 7.5. Q-S1 to Q-S4 are answered and removed: Q-S1 (devices that cannot be opened in the scan) and Q-S2 (standby in 7.4) in the source on 2026-10-07, Q-S3 (the temperature data of 7.4: the SCT status is written, but the NVMe temperature limits exist in the JSON only from 7.5 on) in the source on 2026-10-12, and Q-S4 (`--xall` causes no delay) by the recordings of 2026-10-05 and 2026-10-12. The answers are in [Research 03](docs/research/03-smart-indicators.md) and [Research 06](docs/research/06-test-cluster-recordings.md).

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-S7 | Why does `smartctl --scan-open` leave out a USB device with an unknown bridge (`pve1`) without an entry and without `open_error`, and which devices does it leave out in the same way? | `scan` says `0 skipped` for a drive that the web interface lists; decides whether `scan` should show block devices that the scan omits ([Research 07](docs/research/07-standalone-host-pve1.md)) | Smartctl finds no working device type for it and omits it. Not read in the source. The tool keeps the behavior of ARCHITECTURE section 5 |
| Q-S6 | Which transport does `lsblk` write for iSCSI and Fibre Channel disks, which does the kernel write for NVMe over Fabrics, and does `lsblk` show the pool of a ZFS member and the name of an md array as assumed? | Filter `remote` and the membership of a drive. The test cluster has neither remote disks nor ZFS nor md | `iscsi` and `fc` in `TRAN`; `tcp`, `rdma`, `fc`, `loop` in `/sys/class/nvme/nvmeN/transport`; the pool as `LABEL` of a `zfs_member`, the array as a child of the type `raid1`, `raid5` and so on |
| Q-S5 | Does the device scan with `--scan-open` wake hard disks that are in standby? | The tool promises not to wake sleeping drives. The scan opens every device before the standby check of the drive query applies. Needs a host with hard disks that spin down. The test cluster has none, so the answer has to come from a contributor | It does not. If it does, discovery has to cache the device type and scan without opening |

## Thresholds

Answered or narrowed in milestone M3, some only with feedback from users.

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-T1 | How must the raw value of attribute 188 (command timeout) be decoded on drives that pack several counters into it? | Without decoding, healthy drives would exceed the threshold of 100 | The check uses the decoded value from smartctl's string form where it has several parts; otherwise the number |
| Q-T2 | Are the defect counter thresholds derived from hard disk data appropriate for SATA SSDs? | No public data was found for SSDs | Same thresholds for both |
| Q-T3 | What are sensible thresholds for grown defects on SAS drives? | No public failure-rate data was found | Notice at 1, warning at 100, every increase reported. Checked only against recordings ([Research 08](docs/research/08-public-recordings.md)): the healthy SAS drives have 0, one SAS drive with 56 gets a notice, a parallel SCSI drive with 260 a warning. To be reviewed in M7 |
| Q-T4 | Are the temperature limits per class right, and should limits reported by the drive itself take precedence where available? | Temperature is the most likely source of noise | Fixed limits per class, confirmation in two runs |
| Q-T5 | Are the defaults of `scsi.uncorrected_errors` (warning at 1) and `scsi.pending_defects` (warning at 1) right? | No public failure-rate data was found, and every recording seen has 0 pending defects or no page for them | Warning at the first one, every increase reported, no critical. Checked only against recordings: the healthy SAS drives have 0 uncorrected errors, the parallel SCSI drive with 260 grown defects has 536. To be reviewed in M7 |

## Packaging and operation

None at the moment. Milestone M5 answered Q-P1 in [ADR 0025](docs/adr/0025-sandboxing-of-the-check-service.md) and Q-P2 in [ARCHITECTURE.md](ARCHITECTURE.md) section 13, both on `pve1` on 2026-10-13, and Q-P3 with the package test in CI, also in section 13.

## Hardware RAID

Narrowed in milestone M6. Some of these stay open until users with the hardware contribute recordings. [Research 08](docs/research/08-public-recordings.md) (2026-10-16) narrowed Q-R1 and Q-R2 from the source code of smartmontools and from public recordings, and answered which public recordings have a usable license, the second half of the former Q-R5. Q-R6, whether the WWN of a SAS drive in `lsblk` is its `logical_unit_id`, was answered on the maintainer's TrueNAS host on 2026-10-16; the answer is in [ARCHITECTURE.md](ARCHITECTURE.md) section 4.

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-R1 | How do enclosures and logical volumes behind a MegaRAID controller, and SAS drives read as `megaraid,N`, appear in `--scan-open` and in the drive output, exactly? SATA drives as `sat+megaraid,N` are seen in public recordings of smartmontools 7.1 | Classification and skipping rules ([ADR 0028](docs/adr/0028-logical-volumes-and-enclosures.md)) | From the source code of 7.4 and 7.5, not from recordings: a logical volume has an `open_error` in the scan that asks for `-d megaraid,N`, and the vendor and model of the controller in `lsblk`; read with `--device=scsi` its output has no message, only its inquiry data; an enclosure has the peripheral device type 13; `--scan-open` reports a SATA drive behind the controller as `sat+megaraid,N` and a SAS drive as `megaraid,N`. Also assumed: a drive in JBOD mode has no transport in `lsblk`, and no drive has the vendor field `LSI`. The tests use derived data for all of this |
| Q-R2 | For HPE Smart Array with the `hpsa` and `smartpqi` drivers: which device node is used, can the numbering have gaps within the range 0 to 127 that smartctl accepts, and how does an empty bay answer? | Rules of the probe | Probe from 0 upwards on the controller's device, stop after several consecutive failures, never above 127 |
| Q-R3 | Can NVMe drives behind tri-mode RAID controllers be queried with smartctl 7.4? | Coverage statement in the documentation | Unknown; documented as unknown |
| Q-R4 | When will smartmontools support controllers that use the `mpi3mr` driver (issue 313)? | Dell PERC 12 and Broadcom 96xx are current hardware | Not supported; the tool reports the controller as not queryable |
| Q-R5 | Who can contribute recordings from MegaRAID, HPE, Adaptec and Areca systems? | Evidence level of the hardware support | The public recordings of Research 08 as a start; a call for recordings with M6 |

## Upstream developments to watch

| ID | Topic | Why it matters |
| --- | --- | --- |
| Q-U1 | The health-check framework on the Proxmox VE roadmap, which names "RAID/disk state" and integration into the notification system | Could overlap with this project or offer a better integration point. No design or date was found |
| Q-U3 | Proxmox VE 10 | Expected with the next Debian release. The notify bridge and the template location must be checked against its first beta |

## Verified assumptions that looked risky

Recorded here so that nobody has to check them again.

- Python 3 is a hard, transitive dependency of `pve-manager` and therefore present on every Proxmox VE 9 host ([ADR 0003](docs/adr/0003-implementation-language.md)).
- `smartctl --scan` lists physical drives behind MegaRAID controllers on Linux ([Research 04](docs/research/04-hardware-raid.md)).
- A second package installing templates into the vendor template directory has precedent in `pve-ha-manager` ([Research 01](docs/research/01-notification-integration.md)).
- The REST API has no endpoint for sending a custom notification ([Research 01](docs/research/01-notification-integration.md)).
- smartd on Debian repeats its mail daily by default ([Research 02](docs/research/02-builtin-smart-handling.md)).
- `dh_install` of debhelper 13 copies an entry of an install list whose source is a directory with the name of that directory and without the path it has in the repository: it changes into the parent directory and copies with `cp --parents`, so `src/pve_smart_alert` lands as `/usr/share/pve-smart-alert/pve_smart_alert`. The `PYTHONPATH` of the launcher depends on it, and the package job in CI checks the installed tree.
