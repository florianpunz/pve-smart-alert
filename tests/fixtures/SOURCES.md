# Sources of the fixtures

Every fixture has its origin and its license recorded here ([ADR 0016](../../docs/adr/0016-test-strategy.md), NFR-20).
No fixture contains a real serial number or WWN; a test checks every fixture for it.

## Output of smartctl: `smartctl/`

Recordings, one directory per recording under the controller of its drives (`direct` for directly attached drives, `hba` for drives behind a SAS host bus adapter that smartctl reads directly): `scan.json` from `smartctl --scan-open --json=c`, one file per device from `smartctl -x --json=c -d TYPE DEVICE`, `lsblk.json` from `lsblk -J -O`, where the recording has them, and `recording.json` with the origin, the license and the smartmontools version, and the command line, exit status, protocol and class of every file.
The recordings of the maintainer were written by [`scripts/make_fixtures.py`](../../scripts/make_fixtures.py) from the archives of [`scripts/collect-node-data.sh`](../../scripts/collect-node-data.sh), which stay outside the repository, and are anonymized as [ADR 0023](../../docs/adr/0023-anonymization-of-recordings.md) describes: serial numbers, WWNs, EUI-64s, NGUIDs and UUIDs are replaced by counters in the order of the scan. Nothing else is changed; the JSON is written indented.

| Directory | Origin | Changes | License |
| --- | --- | --- | --- |
| `direct/test-cluster-pve5` | [Research 06](../../docs/research/06-test-cluster-recordings.md): the test cluster of the maintainer, node `pve5`, recorded on 2026-10-05 by the collection script. Fanxiang S301 256GB | Anonymized | AGPL-3.0-or-later |
| `direct/test-cluster-pve6` | Same, node `pve6`. Samsung SSD 750 EVO 500GB, WDC PC SN720 | Anonymized | AGPL-3.0-or-later |
| `direct/test-cluster-pve7` | Same, node `pve7`. Samsung SSD 850 EVO 250GB, two Samsung MZVLW256HEHP (PM961) | Anonymized | AGPL-3.0-or-later |
| `direct/standalone-pve1` | [Research 07](../../docs/research/07-standalone-host-pve1.md): the standalone test host `pve1` of the maintainer, not part of the test cluster, recorded on 2026-10-08 by the collection script. Intenso SSD; a USB device that the scan does not list | Anonymized | AGPL-3.0-or-later |
| `direct/failing-hdd` | Derived by hand from the recording of `test-cluster-pve7`: a hard disk that fails several checks at once, for the tests of the evaluation of milestone M3 and its acceptance step 2. Identity and values replaced, derived on 2026-10-12 | Anonymized and modified | AGPL-3.0-or-later |
| `hba/maintainer-truenas` | [Research 08](../../docs/research/08-public-recordings.md), additions of 2026-10-16: the TrueNAS host `truenas` of the maintainer, own hardware, recorded on 2026-10-16 at 14:52 UTC through the read-only wrapper of the host, with the call of smartctl that the tool makes, not by the collection script. It replaces the recording of 12:09 UTC the same day, which passed `-n standby` for every drive. Three NetApp X371 SAS SSDs behind an LSI SAS2308 HBA (`mpt2sas`) and one Samsung SSD 850 EVO 120GB on the AHCI controller, smartmontools 7.4. The SAS SSDs carry SAS addresses; the WWN of each in `lsblk` is its logical unit id (Q-R6) | Anonymized | AGPL-3.0-or-later |

### Taken from the test data of other projects

These recordings come from the test data of other projects, read at a pinned commit and anonymized by `scripts/make_fixtures.py import` ([ADR 0026](../../docs/adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)). Each fixture has one file of its source, or the files the source shows to belong together; a scan or drive file the source does not have is not made up. `recording.json` names the repository, the commit, the path of every file, the copyright line and the license text, kept in [`licenses/`](licenses/); [THIRD-PARTY-NOTICES.md](../../THIRD-PARTY-NOTICES.md) lists the projects. What each file shows, and why other files of the same sources were not taken, is in [Research 08](../../docs/research/08-public-recordings.md).

| Directory | Origin | Changes | License |
| --- | --- | --- | --- |
| `direct/libblockdev-hgst-husmr3280ass200` | libblockdev, `tests/smart_dumps/HGST_HUSMR3280ASS200.json`. Healthy SAS SSD, smartmontools 7.3 | Anonymized | LGPL-2.1-or-later |
| `direct/libblockdev-toshiba-kpm5xmug400g` | libblockdev, `TOSHIBA_KPM5XMUG400G.json`. Healthy SAS SSD, 7.3 | Anonymized | LGPL-2.1-or-later |
| `direct/libblockdev-seagate-st600mp0036` | libblockdev, `SEAGATE_ST600MP0036.json`. Healthy SAS hard disk, 7.3 | Anonymized | LGPL-2.1-or-later |
| `direct/libblockdev-toshiba-al15seb120ny` | libblockdev, `TOSHIBA_AL15SEB120NY.json`. Healthy SAS hard disk, 7.3 | Anonymized | LGPL-2.1-or-later |
| `direct/libblockdev-wd-wd4001fyyg` | libblockdev, `WD4001FYYG-01SL3.json`. Healthy SAS hard disk, 7.3 | Anonymized | LGPL-2.1-or-later |
| `direct/exporter-hitachi-h109060sesun600g` | smartctl_exporter, `testdata/HITACHI_H109060SESUN600G_9.json`. Healthy SAS hard disk, 7.3 | Serial number, build and platform information and logical unit id replaced by the source; anonymized | Apache-2.0 |
| `direct/exporter-seagate-st373453lc-defects` | smartctl_exporter, `testdata/SEAGATE_ST373453LC_26.json`. Parallel SCSI hard disk with grown defects and uncorrected errors, 7.4 | Serial number, build and platform information replaced by the source; anonymized | Apache-2.0 |
| `direct/exporter-seagate-st373453lc` | smartctl_exporter, `testdata/SEAGATE_ST373453LC_27.json`. Healthy parallel SCSI hard disk, 7.4 | Same | Apache-2.0 |
| `direct/scrutiny-seagate-st4000nm0043` | Scrutiny, `webapp/backend/pkg/models/testdata/smart-scsi.json`. SAS hard disk with grown defects, version not recorded | Anonymized | MIT |
| `intel-rst/scrutiny-raid1-volume` | Scrutiny, `webapp/backend/pkg/models/testdata/smart-raid.json`. Intel RAID 1 volume read as a SCSI device, 7.0 | Anonymized | MIT |
| `megaraid/scrutiny-megaraid-scan` | Scrutiny, `collector/pkg/detect/testdata/smartctl_scan_megaraid.json`. Device scan with two drives behind MegaRAID, 7.1; no drive files | None: the scan has no identifier | MIT |
| `megaraid/scrutiny-megaraid-wd4000fyyx` | Scrutiny, `smart-megaraid0.json` and `smart-megaraid1.json`. Two SATA hard disks behind MegaRAID, 7.1; no scan | Serial numbers replaced by the source with the same value, so both have the same placeholder; anonymized | MIT |
| `megaraid/telegraf-megaraid` | Telegraf, `plugins/inputs/smartctl/testcases_scan/megaraid/response.json` and `testcases_device/megaraid/response.json`. Scan of a MegaRAID host and one SATA hard disk behind it, 7.1 | Anonymized | MIT |

## Scenarios: `../scenarios.py`

The scenario tests of the notification policy replay a host whose drives change from run to run ([ADR 0016](../../docs/adr/0016-test-strategy.md)). The steps are not committed as files: `tests/scenarios.py` derives each of them from a recording above when the tests run, or when `python3 tests/scenarios.py build NAME DIRECTORY` writes them for an acceptance run on a real host. Every step is therefore derived, and its license is that of its base recordings.

| Scenario | Base | Changes |
| --- | --- | --- |
| `pending-sectors` | `direct/standalone-pve1` | The raw value of attribute 197 set to 3 and to 20, an attribute 197 entry with made-up flags added where the drive has none, and the drive removed from the scan and the recording |
| `five-hot` | `direct/standalone-pve1` | Four copies of the drive as `/dev/sdb` to `/dev/sde` with the serial numbers `ANON-SN-0002` to `ANON-SN-0005` and without WWN, and the temperature of all five set to 65 °C |
| `onboard-sata-nvme` | `direct/test-cluster-pve7` | The media and data integrity errors of `nvme0` set to 2 |
| `hba-sas` | `hba/maintainer-truenas` | The grown defect list of `sdc` set to 150 |
| `hpe-smart-array` | `hba/maintainer-truenas` | **Synthetic** host: the SATA SSD `sdd` and the SAS SSD `sdc` given the device fields of a read of `cciss,0` and `cciss,1` on `/dev/sg1`, everything else of the recording taken away, and an empty scan; it is also the recording of the probe tests. Then the raw value of attribute 197 of `cciss,0` set to 3 |
| `unsupported-mpi3mr` | `direct/standalone-pve1` | None in the recording; the host gets a **synthetic** SCSI host with the driver `mpi3mr` (below) |
| `manual-pass-through` | `direct/standalone-pve1`, with one drive each of `megaraid/scrutiny-megaraid-wd4000fyyx` (MIT), `direct/libblockdev-seagate-st600mp0036` and `direct/libblockdev-toshiba-al15seb120ny` (LGPL-2.1-or-later), `direct/test-cluster-pve5`, `direct/test-cluster-pve6` and `hba/maintainer-truenas` | **Derived**: each of the six drives moved to the node and type of a controller other than MegaRAID and cciss (`areca,2` on `/dev/sg2`, `areca,1/1` on `/dev/sg3`, `3ware,1` on `/dev/twa0`, `aacraid,0,0,2` on `/dev/sdc`, `hpt,1/2/3` on `/dev/sdd`, `sssraid,0,1` on `/dev/bsg/sssraid0`), with the `info_name` that the source of smartmontools 7.5 writes for the controller, its serial number renumbered to `ANON-SN-0002` to `ANON-SN-0007` and its WWN and logical unit id removed. The SSSRAID drive is added to the scan, as smartctl lists such drives itself; the others are manual entries of the scenario. A made-up lsblk answer for the logical volumes `/dev/sdc`, with a ZFS pool `tank`, and `/dev/sdd`, next to the recorded `/dev/sda` and `/dev/sdb`. Then the raw value of attribute 197 of the 3ware drive set to 3 and the grown defect list of the Adaptec drive set to 150 |
| `megaraid-jbod` | `megaraid/telegraf-megaraid` (MIT) and `direct/libblockdev-seagate-st600mp0036` (LGPL-2.1-or-later) | A MegaRAID host in which only the SATA drive is recorded; everything else is **derived**. The scan, recorded without `--scan-open`, replaced by what `--scan-open` lists: a logical volume `/dev/sda` with the `open_error` of smartmontools 7.4 and 7.5, the SATA drive as `sat+megaraid,14` and a SAS drive as `megaraid,8`, both on `/dev/bus/6`. The SAS drive is the libblockdev SAS hard disk, **derived**: its device changed to `/dev/bus/6` with type `megaraid,8`, its serial number and logical unit id renumbered to `ANON-SN-0002` and `0x5000c50000000002`. A made-up lsblk answer with the logical volume (vendor `DELL`, model `PERC H730P Mini`). In this scenario the SATA drive is also a block device `/dev/sdc`, a copy of the recorded output, as in JBOD mode |
| `megaraid-id-change` | Same | The same host without `/dev/sdc`; the raw value of attribute 197 of the SATA drive set to 8, then the device IDs changed to `sat+megaraid,15` and `megaraid,9`; then the SAS drive removed from the scan and the recording |
| `megaraid-degraded` | Same | The same host without `/dev/sdc`; the raw value of attribute 197 of the SATA drive set to 3 and the grown defect list of the derived SAS drive set to 150 |

## SCSI hosts of sysfs: `../unit/hosts.py`

The trees below `/sys/class/scsi_host` that the tests of the controllers whose drives cannot be queried read ([ADR 0030](../../docs/adr/0030-controllers-whose-drives-cannot-be-queried.md)) are written by the tests into their temporary directory, from the constants in `tests/unit/hosts.py`, and for a scenario from the SCSI hosts it names in `tests/scenarios.py`, which repeat the values below: `hba-sas` those of the TrueNAS host, `onboard-sata-nvme` those of `pve7`, `unsupported-mpi3mr` those of `MPI3MR_SCSI_HOSTS`, the MegaRAID scenarios a synthetic `megaraid_sas` host 6, and `hpe-smart-array` a synthetic `hpsa` host 1 with the SCSI generic node `sg1`. They hold only the number and the driver of each SCSI host, no identifier. License AGPL-3.0-or-later.

| Constant | Origin |
| --- | --- |
| `TRUENAS_SCSI_HOSTS` | Recorded on 2026-10-16 at 20:04 UTC on the maintainer's TrueNAS host through the command `hosts` of the read-only wrapper ([Research 08](../../docs/research/08-public-recordings.md)): `mpt2sas`, six `ahci`, `ahciem` |
| `CLUSTER_NODE_SCSI_HOSTS` | Recorded in the same session on `pve7` of the test cluster: six `ahci`; `pve5` and `pve6` have two |
| `STANDALONE_SCSI_HOSTS` | Recorded on 2026-10-16 at about 20:40 UTC on `pve-test` from `/sys/class/scsi_host`: two `ahci` and `usb-storage` |
| `MPI3MR_SCSI_HOSTS`, `MIXED_SCSI_HOSTS` | Synthetic: no recording of an `mpi3mr` host exists. `mpi3mr` next to `ahci`, and next to an `mpt3sas` HBA |

## Rendered notifications: `golden/`

The subject, the metadata fields and the body of every kind of notification, written by the renderer from plans that the tests in `tests/unit/test_render.py` build by hand ([ADR 0016](../../docs/adr/0016-test-strategy.md): rendering is compared with golden files). The drives in them are made up, with the placeholder serial numbers of the anonymization. A change to the text or the fields of a notification updates these files: `PVE_SMART_ALERT_UPDATE_GOLDEN=1 make test` writes them, and the diff is reviewed with the change. License AGPL-3.0-or-later.

## State files: `state/`

State files that earlier builds wrote, so that a test reads them with the current code ([ADR 0007](../../docs/adr/0007-state-storage.md)). License AGPL-3.0-or-later.

| File | Origin |
| --- | --- |
| `dev2-megaraid-id-change.json` | Written on 2026-10-16 by the code of 0.5.0~dev2 (commit `299acc2`) in the test frame, after the steps `01-first` to `04-moved` of the scenario `megaraid-id-change`, with the clock of the frame. Schema 1. The drives are those of the scenario, with its placeholder serial numbers and WWNs; written indented with sorted keys, nothing else changed |

## Notification configuration: `pvesh/`

The answers of `pvesh get /cluster/notifications/matchers --output-format json` and `pvesh get /cluster/notifications/targets --output-format json`, one directory per configuration, as `matchers.json` and `targets.json`.
The routing check of [ADR 0020](../../docs/adr/0020-routing-check.md) is tested with them.

| Directory | Origin | Changes | License |
| --- | --- | --- | --- |
| `test-cluster-a` | Configuration A of [Research 06](../../docs/research/06-test-cluster-recordings.md): the test cluster of the maintainer, node `pve7`, recorded by hand on 2026-10-05 | Target names replaced | AGPL-3.0-or-later |
| `test-cluster-b` | Configuration B of Research 06, recorded in the same session. The targets were recorded once in that session, so `targets.json` is the one of `test-cluster-a` | Target names replaced | AGPL-3.0-or-later |
| `test-cluster-c` | Configuration C of Research 06: node `pve7`, recorded on 2026-10-05 by [`scripts/collect-node-data.sh`](../../scripts/collect-node-data.sh) | Target names replaced | AGPL-3.0-or-later |
| `builtin-default` | Derived, not recorded: the built-in default configuration of Proxmox VE, `DEFAULT_CONFIG` in `proxmox-notify/src/context/pve.rs` (`master` on 2026-10-06, [Research 01](../../docs/research/01-notification-integration.md)), written in the form of the recorded answers. That an unchanged built-in entry has the origin `builtin` is assumed (Research 06) | Derived | AGPL-3.0-or-later |

The names of targets that the maintainer chose are replaced by `smtp-relay` and `smtp-provider`. The built-in names `default-matcher` and `mail-to-root` are kept.

## License texts: `licenses/`

The license texts of the projects whose test data is taken above, copied unchanged from their repositories at the commits named in each `recording.json` ([ADR 0026](../../docs/adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)).
