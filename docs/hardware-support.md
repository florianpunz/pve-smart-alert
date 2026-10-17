# Hardware support

Which drives and controllers PVE SMART Alert reads, and how each was verified.
Every controller family named in the documentation carries one of the evidence labels of [ADR 0016](adr/0016-test-strategy.md) (NFR-16):

| Label | Meaning |
| --- | --- |
| Verified on hardware | Tested by the maintainer or a named contributor on a real system |
| Verified by fixtures | Recorded output from a real system passes the scenario tests |
| Experimental | Implemented from documentation; no recorded output yet |
| Not possible | Cannot be supported with smartctl |

The column "Basis" says what the label rests on: a real host the tool ran on, a recording of a real system (own hardware or the public test data of another project), data derived from a recording by changing values or moving a drive behind another controller, synthetic data written for the tests, or nothing.
A fixture proves that recorded output is handled; it does not prove that the tool behaves well on that hardware in every situation (ADR 0016).
The scenario named in the last column runs in `make test` (`tests/scenarios.py`); the fixtures and how each was derived are listed in [tests/fixtures/SOURCES.md](../tests/fixtures/SOURCES.md).
The state of the work is in [ROADMAP.md](../ROADMAP.md).

## Support table

| Family | Driver | How the tool reaches the drives | Label | Basis | Scenario |
| --- | --- | --- | --- | --- | --- |
| SATA drives on the board (AHCI) | `ahci` | The device scan, read directly | Verified on hardware | Real hosts: the acceptance of M2 on the three nodes of the test cluster with 0.2.0 (2026-10-12, [Research 06](research/06-test-cluster-recordings.md)) and on `pve1` (2026-10-08, [Research 07](research/07-standalone-host-pve1.md)), the acceptance of M3 on the real drives of `pve1` and the cluster, and of M4 on `pve1` with 0.4.0 (both 2026-10-12, [ROADMAP.md](../ROADMAP.md), M3 and M4); recordings of those hosts | `onboard-sata-nvme`, `pending-sectors`, `five-hot` |
| NVMe drives on the board | `nvme` | The device scan, read directly | Verified on hardware | Real hosts: the NVMe drives of `pve6` and `pve7` in the acceptance of M2 (Research 06) and of M3, which evaluated them on real hardware (ROADMAP.md, M3); no failing NVMe drive was seen, the findings of the scenario are derived | `onboard-sata-nvme` |
| SAS drives behind a SAS HBA | `mpt2sas` | The device scan, as block devices of the host; the HBA is never reported as a controller that cannot be queried ([ADR 0030](adr/0030-controllers-whose-drives-cannot-be-queried.md)) | Verified by fixtures | Recording of the maintainer's TrueNAS host (three SAS SSDs behind an LSI SAS2308, 2026-10-16, [Research 08](research/08-public-recordings.md)) and its SCSI hosts from sysfs; the tool was not installed there. The grown defects of the scenario are derived | `hba-sas` |
| SATA drives behind a SAS HBA | `mpt2sas`, `mpt3sas` | As SAS drives behind an HBA, with the type `sat` that the scan names | Experimental | No recording: the SATA SSD of the TrueNAS host sits on the AHCI controller of the board | – |
| SAS drives behind an `mpt3sas` HBA | `mpt3sas` | As behind `mpt2sas` | Experimental | No recording of an `mpt3sas` host; the driver is treated as `mpt2sas` (ADR 0030), and its SCSI hosts in the tests are synthetic | – |
| SAS and parallel SCSI drives read directly | – | The device scan, type `scsi` | Verified by fixtures | Public recordings of libblockdev, smartctl_exporter and Scrutiny (Research 08), and the TrueNAS host above | `hba-sas` |
| Broadcom/LSI MegaRAID and Dell PERC up to generation 11: SATA drives | `megaraid_sas` | The device scan, `sat+megaraid,N` on `/dev/bus/H`; in JBOD mode the block device is kept ([ADR 0028](adr/0028-logical-volumes-and-enclosures.md)) | Verified by fixtures | Public recordings of SATA hard disks behind MegaRAID (Telegraf, Scrutiny, smartmontools 7.1); the answer of `--scan-open` and lsblk are derived from the source of smartmontools (Q-R1) | `megaraid-jbod`, `megaraid-id-change`, `megaraid-degraded` |
| The same: SAS drives | `megaraid_sas` | The device scan, `megaraid,N` on `/dev/bus/H` | Experimental | Derived only: a recorded SAS hard disk of libblockdev moved behind the controller; no recording of a SAS drive read as `megaraid,N` exists (Research 08, Q-R1) | `megaraid-degraded`, `megaraid-id-change` |
| The same: logical volumes and enclosures | `megaraid_sas` | Skipped with a reason, by lsblk and by the scan (ADR 0028) | Experimental | The logical volume and the enclosure are derived from the source of smartmontools; the recorded Telegraf scan was made without `--scan-open` (Q-R1) | `megaraid-jbod` |
| Intel RST RAID volume | – | Skipped as a logical volume by its inquiry data (ADR 0028) | Experimental | One public recording of Scrutiny, made on Windows (smartmontools 7.0), replayed by the tests of discovery; how such a volume appears to smartctl on Linux is not known (Q-R10) | – |
| HPE Smart Array | `hpsa` | The probe of `cciss,N` on the SCSI generic node of the controller, on by default, switched off with `probe_cciss = false` ([ADR 0032](adr/0032-hpe-smart-array-probe.md)) | Experimental | Synthetic: two drives of the TrueNAS recording given the device fields of a `cciss,N` read; the empty bay is modelled on the source of smartmontools. No HPE host was ever recorded (Q-R2) | `hpe-smart-array` |
| HPE Smart Array | `smartpqi` | Named by `scan` and `doctor`, not probed. A manual entry can name `cciss,N`, but whether smartctl reads a drive that way is not known | Experimental | Implemented from ADR 0032 only as far as naming the controller; no source and no recording shows that `cciss,N` works there (Q-R2) | – |
| HPE Smart Array, old driver | `cciss` | A manual entry, `cciss,N` on `/dev/cciss/c0d0` as smartctl(8) shows | Experimental | Implemented from smartctl(8); not tested beyond the validation of the entry | – |
| Adaptec / Microchip | `aacraid` | A manual entry, `aacraid,H,L,ID` on the block device of the controller ([ADR 0034](adr/0034-manual-entries-of-other-pass-through-types.md), Proposed) | Experimental | Derived: a recorded SAS SSD moved behind the controller; what smartctl writes into the device fields of such a read is not known (Q-R9) | `manual-pass-through` |
| Areca | `arcmsr` | A manual entry, `areca,N` or `areca,N/E` on `/dev/sgN` (ADR 0034) | Experimental | Derived: a recorded SATA and a recorded SAS hard disk (Q-R9) | `manual-pass-through` |
| 3ware | `3w-*` | A manual entry, `3ware,N` on `/dev/twaN`, `/dev/twlN` or `/dev/tweN` (ADR 0034) | Experimental | Derived: a recorded SATA SSD (Q-R9) | `manual-pass-through` |
| HighPoint RocketRAID | – | A manual entry, `hpt,L/M` or `hpt,L/M/N` on the block device of the controller (ADR 0034) | Experimental | Derived: a recorded SATA SSD (Q-R9) | `manual-pass-through` |
| SSSRAID | `sssraid` | The device scan, `sssraid,E,S` on `/dev/bsg/sssraidN`, new and experimental in smartmontools 7.4 (ADR 0034) | Experimental | The scan of these drives is read in the source of smartmontools 7.4 and 7.5 ([Research 04](research/04-hardware-raid.md), addition of 2026-10-17); the drive of the scenario is a recorded SAS hard disk, derived (Q-R9) | `manual-pass-through` |
| Broadcom MegaRAID 96xx, Dell PERC 12 | `mpi3mr` | Reported in `scan`, `doctor` and as `tool.unsupported_controller` (ADR 0030); drives the controller exposes directly are monitored if the scan lists them | Not possible | smartctl cannot read the drives behind it in RAID mode (smartmontools issue 313, Q-R4). The detection rests on synthetic sysfs trees; the HBA personality is Q-R7 | `unsupported-mpi3mr` |
| JMicron RAID port multiplier and USB RAID bridge | – | Never read: a manual entry with `jmb39x` or `jms56x` is refused (ADR 0034) | Not possible | smartctl reads these drives only by writing to a sector of the RAID volume (smartctl(8) of 7.4 and 7.5), and the tool only reads drives ([ADR 0012](adr/0012-read-only-and-coexistence-with-smartd.md)) | – |
| Drives behind USB bridges | `usb-storage`, `uas` | The device scan, if it lists the drive; such a drive is never reported as missing ([ADR 0017](adr/0017-scope-of-version-1.md)) | Experimental | No recording of a USB drive that smartctl can read; the USB device of the KVM-over-IP device of `pve1` and `pve5` is not listed by the scan (Research 07, Q-S7) | – |

### What is not known yet

- NVMe drives behind a tri-mode MegaRAID controller (Q-R3). Nothing was found about how smartctl reads them, and the tool has nothing for them beyond what the scan lists. They are drives of the MegaRAID family, whose labels above cover SATA and SAS drives only; they carry no label of their own until something is built for them.
- What a logical volume of an HPE, Adaptec, Areca, HighPoint or SSSRAID controller answers when the tool reads it. The scan of smartctl lists such a volume as an ordinary `/dev/sdX` of type `scsi` or `sat`, and a 3ware volume with an `open_error` that asks for `-d 3ware,N` ([Research 04](research/04-hardware-raid.md), addition of 2026-10-17); unless its inquiry data are among those of [ADR 0028](adr/0028-logical-volumes-and-enclosures.md), it is monitored as a drive or skipped as `no-smart`. The scenarios list no such volume (Q-R9).

## Recordings wanted

The labels "Experimental" above stay until someone records a real system.
A recording turns a family into "Verified by fixtures": it becomes a fixture, a scenario replays it with the same calls, since the archive names the device and type each drive was read with, and the label changes with the pull request that adds it.
Wanted most, in this order:

1. MegaRAID or PERC with SAS drives, recorded with the scan of `--scan-open`, so that the derived SAS drive, the logical volume and the enclosure can be replaced by real output (Q-R1).
2. HPE Smart Array with `hpsa`, and with `smartpqi` (Q-R2).
3. Adaptec (`aacraid`) and Areca (`arcmsr`).
4. A controller with `mpi3mr` in HBA personality (Q-R7).
5. NVMe drives behind a tri-mode controller (Q-R3).
6. 3ware, HighPoint, SSSRAID, and an `mpt3sas` HBA.

### How to record a host

On the host, as root, with the tool installed:

1. Make the drives behind the controller known to the tool. The scan lists MegaRAID and SSSRAID drives by itself; for the other controllers, add a `[[discovery.device]]` entry per drive to `/etc/pve-smart-alert/config.toml`, with the node and type smartctl(8) names for the controller. `dump-fixture` records the scan and the manual entries, not the drives that only the HPE probe finds, so add those as entries of the form `cciss,N` as well; the line `HPE Smart Array:` of `pve-smart-alert scan` names the device IDs the probe found. The timer reads the entries too, from its next run on; if you remove them again afterwards, each of their drives is reported missing once.
2. Run `pve-smart-alert dump-fixture --all --output /root`. It writes one archive, `/root/<name>.tar.gz`, with the device scan, lsblk and the output of the call the tool makes for each drive, also of a drive that cannot be read.
3. Look at the archive before you share it. Serial numbers, WWNs and UUIDs are replaced by placeholders, and nothing is written when a real value is left ([ADR 0023](adr/0023-anonymization-of-recordings.md)). Model names, firmware versions and the node name are kept.
4. Add the drivers of the SCSI hosts, which the archive does not contain: the output of `grep . /sys/class/scsi_host/host*/proc_name`, and the model of the controller from `lspci -nn`.
5. Attach the archive and that output to an issue, with the controller model, its mode (RAID, JBOD or HBA) and the version of smartmontools.

By contributing a recording you agree that it becomes part of the project under its license, AGPL-3.0-or-later ([ADR 0015](adr/0015-license.md)), as `dump-fixture` writes into the archive. Whether the issue tracker is open to everyone depends on whether the repository is public yet ([ROADMAP.md](../ROADMAP.md), M0).

Nothing in this procedure writes to a drive or changes a setting of a drive. On the host it adds the entries to the configuration of the tool and writes the archive; the runs of the timer keep their state as always, and smartctl itself creates the device nodes it needs for some controllers, such as `/dev/aacH` for Adaptec and the nodes of a 3ware controller (Research 04, addition of 2026-10-17).
