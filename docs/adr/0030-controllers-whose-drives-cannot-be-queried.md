# ADR 0030: Detect controllers whose drives cannot be queried from the driver of the SCSI host

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR 0005](0005-drive-discovery-and-identity.md), [ADR 0028](0028-logical-volumes-and-enclosures.md)

## Context

FR-109 asks that `pve-smart-alert scan` and `pve-smart-alert doctor` say so when a controller is present whose drives cannot be queried with smartctl, and the check catalog has the tool condition `tool.unsupported_controller` (notice) for it. Without it, a host whose drives sit behind such a controller looks healthy: the device scan lists only a virtual drive, and the tool monitors nothing without a word.

What is known about such controllers ([Research 04](../research/04-hardware-raid.md), [Research 08](../research/08-public-recordings.md)):

- Behind a Dell PERC H965i with the driver `mpi3mr` in RAID mode, smartctl lists only the virtual drive and does not show the physical drives. **Verified** in smartmontools issue 313, which is open and covers exactly that case, one RAID 0 virtual drive; Dell says there that the controller does not block smartctl, but that the tool would have to use pass-through commands to reach the drives behind it.
- The same driver runs Broadcom 9600-series cards, which also have an "Enhanced HBA Personality" in which the drives are exposed to the system (**Reported** in a TrueNAS forum thread on a 9600-24i). Whether smartctl reads the drives in that personality is not recorded anywhere (Q-R7).
- The drives behind `hpsa` and `smartpqi` (HPE Smart Array), `aacraid` (Adaptec) and `arcmsr` (Areca) can be queried, with types that the scan does not produce: the HPE probe of milestone M6, slice 5, and manual device entries.
- A controller in HBA or IT mode needs no type at all: its drives are plain SATA or SAS drives to smartctl.

The kernel names the driver of every SCSI host in `/sys/class/scsi_host/hostN/proc_name`. The tool already reads it for the location of a drive behind MegaRAID ([ADR 0028](0028-logical-volumes-and-enclosures.md)). It reads no drive and needs no program, and so no smartctl.

The maintainer's hosts show what a host normally has there (recorded on 2026-10-16, Research 08): the TrueNAS host has `mpt2sas` for its LSI SAS2308 HBA, six `ahci` hosts and one `ahciem`; the cluster nodes have only `ahci`; the standalone host `pve-test` has two `ahci` hosts and `usb-storage`. `ahciem` was seen only on the TrueNAS SCALE kernel; it is taken for the enclosure management of AHCI, but where it comes from was not checked in kernel source. No recording of an `mpi3mr` host exists.

The maintainer decided on 2026-10-16, after `mpt2sas` and `ahciem` were seen on the TrueNAS host, that `mpt2sas` and `mpt3sas` are never reported as unsupported and that `ahciem` produces no warning and no finding.

## Options considered

1. **Report every driver the tool does not know.** Every new kernel or HBA would warn, `ahciem` included, and a warning that is wrong on most hosts is ignored on all of them.
2. **Infer it from the scan**, for example a RAID volume without physical drives next to it. A MegaRAID controller in RAID mode looks the same until its drives are read, and the scan of an `mpi3mr` host was never recorded.
3. **A list of drivers whose drives cannot be queried**, read from `proc_name`; everything else is not reported.

## Decision

Option 3.

- The SCSI hosts are the directories `hostN` below `/sys/class/scsi_host`, and the driver of each is its `proc_name`. A missing directory means no SCSI host. One that cannot be read is no error of a run and no finding.
- A driver is reported only when it is on the list of drivers whose drives cannot be queried. The list holds `mpi3mr`, with the reason, the drives the limitation is known for, and the source (smartmontools issue 313). It is kept in one place in the code and grows only with a source that says the drives cannot be queried, not merely that the tool does not probe them.
- Every `mpi3mr` host is reported, whatever its personality. The text claims no more than issue 313 shows: smartctl cannot read the drives behind it in RAID mode, and drives it exposes directly are monitored if the scan lists them.
- Never reported: `mpt2sas` and `mpt3sas`, HBAs whose drives smartctl reads directly; `ahciem`; `hpsa`, `smartpqi`, `aacraid` and `arcmsr`, whose drives are reached with explicit types; and every driver not on the list. Unknown is not unsupported.
- The driver name is untrusted text of the host: control characters are removed and it is cut to 64 characters before it is compared or shown.
- `pve-smart-alert scan` prints one line per such host above the devices, naming the SCSI host and the driver, which drives smartctl cannot read and that they are not monitored, and the upstream limitation. When sysfs cannot be read, it prints one line `Without SCSI hosts:` with the error.
- `pve-smart-alert doctor` has a line `controllers`: `warn` with the same text and the link to the upstream issue when such a host is present, `ok` with the number of SCSI hosts and their drivers otherwise, `skip` when sysfs cannot be read. A warning, not a failure: the tool itself works.
- `pve-smart-alert check` raises `tool.unsupported_controller`, notice, on the pseudo-device of the tool: one condition for all such hosts, whose text names each of them. It follows the policy of every condition: reminded, and cleared with a recovery once no such host is left.
- The SCSI hosts are read in every run, also while smartctl is missing, because they need no smartctl. When sysfs cannot be read, the condition is not evaluated in that run: an active one stays as it is, neither recovered nor raised again, and none is raised.

## Consequences

- A host with an `mpi3mr` controller in RAID mode is told why its drives are not monitored, in `scan`, in `doctor` and once as a notification, instead of silence.
- **An `mpi3mr` host in HBA personality is reported as well**, although its drives may be monitored, if smartctl reads them there. The text names the drives in RAID mode only and says that drives the scan lists are monitored, so the notice does not claim they are lost. Q-R7 in [OPEN-QUESTIONS.md](../../OPEN-QUESTIONS.md) asks whether such a host should be left out.
- The hosts recorded so far, the cluster nodes, `pve-test` and the TrueNAS host, report nothing new; `doctor` adds one line `ok` for them.
- A controller whose drives cannot be queried but whose driver is not on the list is not reported. That is the price of not warning about every unknown driver; the list grows with evidence.
- A controller with the driver `mpi3mr` is reported even when smartmontools gains support for it, until the list is changed. Q-R4 watches issue 313.
- A missing smartctl or an unreadable sysfs does not end the condition with a false recovery, and does not send a new notice when it is over.
- The condition text names every host, so a second such host changes the text, not the severity; it is not notified again before its reminder.

## Revisit when

- smartmontools supports `mpi3mr` (issue 313), or a source shows another driver whose drives cannot be queried.
- A recording shows whether smartctl reads the drives of an `mpi3mr` controller in HBA personality (Q-R7).
- A user reports a warning for a driver whose drives smartctl does read.
