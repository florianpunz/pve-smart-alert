# ADR 0032: Probe the drives behind an HPE Smart Array controller

- Status: Accepted
- Date: 2026-10-17
- Extends: [ADR 0005](0005-drive-discovery-and-identity.md), [ADR 0016](0016-test-strategy.md), [ADR 0028](0028-logical-volumes-and-enclosures.md), [ADR 0029](0029-notification-field-device-id.md)

## Context

FR-103 asks the tool to find the physical drives behind an HPE Smart Array controller by probing, experimental in version 1 and possible to switch off; the sources of [ARCHITECTURE.md](../../ARCHITECTURE.md) section 5 have named the probe `cciss,N` since milestone M2. Such a controller in RAID mode hides its physical drives from the device scan ([Research 04](../research/04-hardware-raid.md)), and smartctl reaches them with `-d cciss,N`, where `N` is the position of the drive in the device list of the controller.

What is known, checked in the source of smartmontools 7.4 and 7.5 and in its manual page on 2026-10-17 ([Research 08](../research/08-public-recordings.md)):

- `-d cciss,N` accepts `0 <= N <= 127` (`os_linux.cpp`, 7.5 lines 3579 to 3584) and wraps the device as `sat,auto`, so a SATA drive behind the controller is read through SAT (line 3584).
- With the driver `hpsa` the device node is the SCSI generic node of the controller: `smartctl -a -d cciss,0 /dev/sg2` (`smartctl.8.in`, lines 685 to 701).
- `N` indexes the list that `CISS_REPORT_PHYS` answers with (`cciss.cpp`, `cciss_getlun`, lines 197 to 246). A position beyond the list makes the ioctl fail with `-ENXIO` ("give up, assume no device there", lines 87 and 145), which smartctl reports as a failed open with exit status 2 (`smartctl.cpp`, lines 1552 to 1561). The IDs are therefore the positions in the list of devices that are present, not bay numbers.
- smartctl itself expects the option on hosts with the driver `hpsa` only: `is_hpsa_in_raid_mode` compares the `proc_name` with `hpsa`, derives the host number from the SCSI device name `H:C:T:L`, and asks for `-d cciss,N` when the volume reports a RAID level (`os_linux.cpp`, lines 3363 to 3414 and 3475 to 3477). The same controllers run with the driver `smartpqi` on other hosts, and neither a source nor a recording shows that the pass-through works there.
- `-n` (`--nocheck`) is accepted for ATA and SCSI devices and ignored where the power mode check is not supported (`smartctl.8.in`, lines 891 and 930); the tool passes `--nocheck=standby` for ATA and SAT types only (ADR 0004).

The maintainer decided on 2026-10-17 on three points: the probe runs only where smartctl itself supports it, that is on hosts with the driver `hpsa`; a host with `smartpqi` is detected and named in `scan` and `doctor` but not probed until a source or a recording shows that it works (Q-R2); and `cciss,N` gets no `--nocheck=standby`.

## Options considered

1. **Probe `hpsa` and `smartpqi` alike.** Wider coverage, but it would send the pass-through ioctl to a controller whose driver smartctl does not itself use for it, and no recording shows what comes back.
2. **Probe `hpsa`, name `smartpqi`.** The tool probes where smartctl's own rule points, and a host with `smartpqi` is told what it can do instead: add the drives as manual entries.
3. **Do not probe at all.** FR-103 would not be met, and an administrator would have to look up device IDs by hand.

## Decision

Option 2, with the following rules.

- **Scope.** A SCSI host whose driver is `hpsa` is probed; the driver is read from `/sys/class/scsi_host/hostN/proc_name` ([ADR 0030](0030-controllers-whose-drives-cannot-be-queried.md)). A host with `smartpqi` is not probed: `scan` and `doctor` name it, the reason and the way out, which is a manual entry in `[[discovery.device]]` (FR-104). Every other driver is no Smart Array controller or an HBA.
- **The node.** The probe reads the lowest-numbered `/dev/sgN` whose SCSI device belongs to that host, found through `/sys/class/scsi_generic/sgN/device`; the kernel names the SCSI device `H:C:T:L` and the link's target ends in that name. smartctl derives the host of a block device the same way (`is_hpsa_in_raid_mode`). Any node of the controller reaches it, because the pass-through is an ioctl that looks the drive up in the device list of the controller; the lowest number makes the choice the same within a run and as stable as the numbering of the nodes itself. The identity of a drive does not depend on the node (FR-105): a changed node changes its location, not its state.
- **The reads.** `cciss,0` upwards, one call per ID with the configured detail level, until `CONSECUTIVE_FAILURES` = 3 IDs in a row answer nothing, and never above 127. Three, because a drive that is present but answers nothing must not end the probe, and an ID that is not there fails fast, so three failing calls are what a controller with no drive left costs at most. A drive that answers goes through the normal examination: logical volume, non-disk, no SMART, exclude rules and identity apply to it as to every other device, and a drive that the scan found as well is kept once (FR-106).
- **No `--nocheck=standby`.** A `cciss,N` device can be a SAS or a SATA drive, and the option can end a SCSI call without data, which is why the tool passes it for ATA and SAT types only (ADR 0004). A SATA drive in standby behind the controller is woken by the probe.
- **The configuration.** `[discovery] probe_cciss`, default `true`; it is the only key of the section that is not a list. `false` stops the probe, and the controllers are still named in `scan` and `doctor`. The probe is experimental in version 1 (ADR 0016).
- **The location and the field.** `pass_through_id` reads `N` from `cciss,N` and `sat+cciss,N`, so `scan` shows `Location: /dev/sg1 (hpsa), device 0` and a notification about one drive carries `device-id` = `N`, as [ADR 0029](0029-notification-field-device-id.md) says for every pass-through type.
- **The texts.** `scan` prints one `HPE Smart Array:` line per controller: the node and the IDs it read, or why it was not probed. `doctor` has the line `probe`: `ok` when there is no such controller, when the probe runs, or when it is switched off; `warn` when the probe should run and cannot (no SCSI generic node) or cannot be used (a `smartpqi` host), with the advice that names the way out; `skip` when sysfs cannot be read.
- **The evidence.** The source only, and synthetic fixtures: no output of an HPE host was ever recorded. The test frame derives the outputs of two drives from the recording of the maintainer's TrueNAS host and rewrites their device fields to the pass-through; an ID that the recording does not have is the empty bay, which the fake smartctl answers as smartctl does, with a failed open and exit status 2. The `--info` outputs of Starosdev/scrutiny stay evidence only ([Research 08](../research/08-public-recordings.md), [ADR 0026](0026-recordings-of-scsi-drives-and-of-other-projects.md)).

## Consequences

- A host with an `hpsa` controller in RAID mode monitors its physical drives without any configuration, and its notifications name the controller and the device ID, so a matcher can select one of them.
- A host with `smartpqi` is not monitored automatically. `scan` and `doctor` say so and name the manual entry; the tool claims nothing about whether the pass-through would work there (Q-R2).
- On such hosts the probe costs one smartctl call per drive and up to three failing calls in each run. It is the only part of a run that reads a device the scan did not name.
- A SATA drive in standby behind the controller is woken, because the probe does not pass `--nocheck=standby` for `cciss,N` (FR-203 applies to the types the tool knows as ATA).
- A drive that is present but answers nothing is indistinguishable from an empty bay: it is not reported, and it costs one of the three failures. A controller with three such drives in a row is not probed further.
- How smartctl lists the logical volume of an HPE controller in the device scan is not recorded. The probe does not change that listing, the synthetic fixture lists nothing, and Q-R2 keeps the question.
- The probe is read-only like everything else: one call per device with the options of ADR 0004 and no option that changes a drive.

## Revisit when

- A source or a recording shows that `-d cciss,N` works with the driver `smartpqi`, or shows how an empty bay answers in the tool's own call and how the scan lists the logical volume; Q-R2 then closes.
- A recording of an HPE host exists: it becomes a fixture, and the synthetic one is replaced by it.
- A controller reports more than 127 devices, which smartctl itself does not accept.
