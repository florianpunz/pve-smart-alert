# Open questions

Everything that could not be settled during planning.
Each entry says why it matters, what is assumed until it is answered, and when it gets answered.
Answered entries are removed from this file; the answer goes into the document it affects, and into a new decision record if it changes a decision.

Last updated: 2026-10-03.

## For the maintainer

None at the moment.

The questions Q-M1 to Q-M8 were answered on 2026-10-03. The answers are recorded in [ADR 0018](docs/adr/0018-project-name.md) (name), [ADR 0019](docs/adr/0019-repository-hosting.md) (repository), the confirmations in the [index of decision records](docs/adr/README.md) (license, template files, smartd), [PROJECT.md](PROJECT.md) (copyright holder) and the test environment section of [ROADMAP.md](ROADMAP.md).

## Notification route

Answered in milestone M1 on a real host.

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-N1 | Does a call to `PVE::Notify::notify` from a separate root process work on Proxmox VE 9.2 without further initialization? | Basis of the primary transport. Verified only in source code and in a forum report | Yes |
| Q-N2 | Does the notification library write its lines "notified via target" and "could not notify via target" to the standard error of the bridge process, and in which exact format? | The only feedback about delivery. The fallback and retry rules depend on it ([ADR 0008](docs/adr/0008-notification-integration.md)) | Yes, readable on standard error |
| Q-N3 | What exactly happens when a template is missing: does the call return success, and what is logged? | This is the most likely failure after a Proxmox VE upgrade. It must lead to the fallback | The call succeeds and the error is only logged |
| Q-N4 | How long can the call block when an SMTP or webhook target is slow or unreachable? | Sets the timeout of the bridge | 120 seconds is enough |
| Q-N5 | How do custom notifications behave in the web interface: is a matcher with a regex on `type` shown and editable normally, and what happens when pmxcfs has no quorum or is not running? | Usability of routing, and behavior in a degraded cluster | Regex matchers work; without pmxcfs the bridge fails and the fallback is used |
| Q-N6 | Do the Proxmox developers plan a supported interface for custom notifications, or the "notification registry" mentioned in their source code? | Would replace the bridge with something stable | Unknown. To be asked on the Proxmox forum or development list once M1 has produced concrete findings |

## smartctl output and discovery

Answered in milestone M2 with recordings from the test cluster.

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-S1 | What does `smartctl --scan-open --json` of version 7.4 contain for each device, and how do devices appear that cannot be opened? | Input format of discovery | An array `devices` with `name`, `info_name`, `type`, `protocol` |
| Q-S2 | How does version 7.4 report a drive in standby when `--nocheck=standby` is given, in JSON and in the exit status? | Distinguishing "asleep" from "unreadable" | Exit status 2 and a message in the JSON |
| Q-S3 | Which JSON keys carry the ATA device statistics (wear), the SCT temperature data and the NVMe self-test log in 7.4? Are the NVMe temperature thresholds of the drive in the JSON? | Sources of the wear, temperature and self-test checks | Present under protocol-specific keys; NVMe thresholds not available before 7.5 |
| Q-S4 | Does `--xall` cause errors, delays or exit status bit 2 on the cluster's drives, compared with `--all`? | Choice of the default detail level ([ADR 0004](docs/adr/0004-smartctl-json-as-data-source.md)) | `--xall` is safe as default |
| Q-S5 | Does the device scan with `--scan-open` wake hard disks that are in standby? | The tool promises not to wake sleeping drives. The scan opens every device before the standby check of the drive query applies. Needs a host with hard disks that spin down. The test cluster has none, so the answer has to come from a contributor | It does not. If it does, discovery has to cache the device type and scan without opening |

## Thresholds

Answered or narrowed in milestone M3, some only with feedback from users.

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-T1 | How must the raw value of attribute 188 (command timeout) be decoded on drives that pack several counters into it? | Without decoding, healthy drives would exceed the threshold of 100 | The check uses the decoded value from smartctl's string form where it has several parts; otherwise the number |
| Q-T2 | Are the defect counter thresholds derived from hard disk data appropriate for SATA SSDs? | No public data was found for SSDs | Same thresholds for both |
| Q-T3 | What are sensible thresholds for grown defects on SAS drives? | No public data was found | Notice at 1, warning at 100, every increase reported |
| Q-T4 | Are the temperature limits per class right, and should limits reported by the drive itself take precedence where available? | Temperature is the most likely source of noise | Fixed limits per class, confirmation in two runs |

## Packaging and operation

Answered in milestone M5.

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-P1 | Which systemd sandboxing options can be used without breaking mail submission through the local mail system or the notification targets? | Hardening is desirable, but options that block privilege changes are known to break mail submission on some setups | Only priority and run-time limits are set until tested |
| Q-P2 | Does the timer start a run immediately when the package is installed on a host that has been up for a while, and what happens on a package upgrade? | The first-run summary should arrive shortly after installation, and an upgrade should not cause surprises | Yes; an upgrade triggers one ordinary run |
| Q-P3 | Can the package be installed and tested in a clean container with the Proxmox VE package repository in CI? | Needed for the automated package test ([ADR 0016](docs/adr/0016-test-strategy.md)) | Yes, with the public no-subscription repository |

## Hardware RAID

Narrowed in milestone M6. Some of these stay open until users with the hardware contribute recordings.

| ID | Question | Why it matters | Assumed until answered |
| --- | --- | --- | --- |
| Q-R1 | How do SATA drives, enclosures and logical volumes behind a MegaRAID controller appear in `--scan-open` and in the drive output, exactly? | Classification and skipping rules | SATA drives as `sat+megaraid,N`; logical volumes and enclosures recognizable by device type and missing SMART capability |
| Q-R2 | For HPE Smart Array with the `hpsa` and `smartpqi` drivers: which device node is used, what is the valid range of `N`, can the numbering have gaps, and how does an empty bay answer? | Rules of the probe | Probe from 0 upwards on the controller's device and stop after several consecutive failures |
| Q-R3 | Can NVMe drives behind tri-mode RAID controllers be queried with smartctl 7.4? | Coverage statement in the documentation | Unknown; documented as unknown |
| Q-R4 | When will smartmontools support controllers that use the `mpi3mr` driver (issue 313)? | Dell PERC 12 and Broadcom 96xx are current hardware | Not supported; the tool reports the controller as not queryable |
| Q-R5 | Who can contribute recordings from MegaRAID, HPE, Adaptec and Areca systems, and which public recordings have a usable license? | Evidence level of the hardware support | Scrutiny's test data as a start; a call for recordings with M6 |

## Upstream developments to watch

| ID | Topic | Why it matters |
| --- | --- | --- |
| Q-U1 | The health-check framework on the Proxmox VE roadmap, which names "RAID/disk state" and integration into the notification system | Could overlap with this project or offer a better integration point. No design or date was found |
| Q-U2 | The smartmontools version in Proxmox VE | Version 7.5 adds vendor-neutral wear and spare values and fixes an NVMe self-test log problem |
| Q-U3 | Proxmox VE 10 | Expected with the next Debian release. The notify bridge and the template location must be checked against its first beta |

## Verified assumptions that looked risky

Recorded here so that nobody has to check them again.

- Python 3 is a hard, transitive dependency of `pve-manager` and therefore present on every Proxmox VE 9 host ([ADR 0003](docs/adr/0003-implementation-language.md)).
- `smartctl --scan` lists physical drives behind MegaRAID controllers on Linux ([Research 04](docs/research/04-hardware-raid.md)).
- A second package installing templates into the vendor template directory has precedent in `pve-ha-manager` ([Research 01](docs/research/01-notification-integration.md)).
- The REST API has no endpoint for sending a custom notification ([Research 01](docs/research/01-notification-integration.md)).
- smartd on Debian repeats its mail daily by default ([Research 02](docs/research/02-builtin-smart-handling.md)).
