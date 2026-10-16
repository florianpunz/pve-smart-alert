# ADR 0030: Detect controllers whose drives cannot be queried from the driver of the SCSI host

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR 0005](0005-drive-discovery-and-identity.md), [ADR 0028](0028-logical-volumes-and-enclosures.md)

## Context

FR-109 asks that `pve-smart-alert scan` and `pve-smart-alert doctor` say so when a controller is present whose drives cannot be queried with smartctl, and the check catalog has the tool condition `tool.unsupported_controller` (notice) for it. Without it, a host whose drives sit behind such a controller looks healthy: the device scan lists only a virtual drive, and the tool monitors nothing without a word.

What is known about such controllers ([Research 04](../research/04-hardware-raid.md)):

- Behind controllers with the driver `mpi3mr` (Broadcom MegaRAID 96xx, Dell PERC 12 such as the H965i), smartctl neither lists nor queries the physical drives; only the virtual drive appears. **Verified** in smartmontools issue 313, which is open.
- The drives behind `hpsa` and `smartpqi` (HPE Smart Array), `aacraid` (Adaptec) and `arcmsr` (Areca) can be queried, with types that the scan does not produce: the HPE probe of milestone M6, slice 5, and manual device entries.
- A controller in HBA or IT mode needs no type at all: its drives are plain SATA or SAS drives to smartctl.

The kernel names the driver of every SCSI host in `/sys/class/scsi_host/hostN/proc_name`. The tool already reads it for the location of a drive behind MegaRAID ([ADR 0028](0028-logical-volumes-and-enclosures.md)). It reads no drive and needs no program.

The maintainer's hosts show what a host normally has there (recorded on 2026-10-16, [Research 08](../research/08-public-recordings.md)): the TrueNAS host has `mpt2sas` for its LSI SAS2308 HBA, six `ahci` hosts and one `ahciem`, the enclosure management pseudo-host that newer kernels add for an AHCI controller; the cluster nodes have only `ahci`. No recording of an `mpi3mr` host exists.

The maintainer decided on 2026-10-16, after `mpt2sas` and `ahciem` were seen on the TrueNAS host, that `mpt2sas` and `mpt3sas` are never reported as unsupported and that `ahciem` produces no warning and no finding.

## Options considered

1. **Report every driver the tool does not know.** Every new kernel or HBA would warn, `ahciem` included, and a warning that is wrong on most hosts is ignored on all of them.
2. **Infer it from the scan**, for example a RAID volume without physical drives next to it. A MegaRAID controller in RAID mode looks the same until its drives are read, and the scan of an `mpi3mr` host was never recorded.
3. **A list of drivers whose drives cannot be queried**, read from `proc_name`; everything else is not reported.

## Decision

Option 3.

- The SCSI hosts are the directories `hostN` below `/sys/class/scsi_host`, and the driver of each is its `proc_name`. Reading them is best effort: a missing directory means no SCSI host; one that cannot be read is no error of a run and no finding, and `doctor` reports its line as skipped.
- A driver is reported only when it is on the list of drivers whose drives cannot be queried. The list holds `mpi3mr`, with the reason and the source (smartmontools issue 313). It is kept in one place in the code and grows only with a source that says the drives cannot be queried, not merely that the tool does not probe them.
- Never reported: `mpt2sas` and `mpt3sas`, HBAs whose drives smartctl reads directly; `ahciem`, which is no drive controller; `hpsa`, `smartpqi`, `aacraid` and `arcmsr`, whose drives are reached with explicit types; and every driver not on the list. Unknown is not unsupported.
- The driver name is untrusted text of the host: control characters are removed and it is cut to 64 characters before it is compared or shown.
- `pve-smart-alert scan` prints one line per such host above the devices, naming the SCSI host and the driver, that smartctl cannot read the drives behind it and that they are not monitored, and the upstream limitation.
- `pve-smart-alert doctor` has a line `controllers`: `warn` with the same text and the link to the upstream issue when such a host is present, `ok` with the number of SCSI hosts and their drivers otherwise, `skip` when sysfs cannot be read. A warning, not a failure: the tool itself works.
- `pve-smart-alert check` raises `tool.unsupported_controller`, notice, on the pseudo-device of the tool: one condition for all such hosts, whose text names each of them. It follows the policy of every condition: reminded, and cleared with a recovery once no such host is left. The SCSI hosts are read by discovery, with the paths it reads lsblk and sysfs with; while smartctl is missing no discovery runs, and the condition is not raised, as `tool.scan_failed` is not.

## Consequences

- A host with an `mpi3mr` controller is told why its drives are not monitored, in `scan`, in `doctor` and once as a notification, instead of silence.
- The hosts recorded so far, the cluster nodes and the TrueNAS host, report nothing new; `doctor` adds one line `ok` for them.
- A controller whose drives cannot be queried but whose driver is not on the list is not reported. That is the price of not warning about every unknown driver; the list grows with evidence.
- A controller with the driver `mpi3mr` is reported even when smartmontools gains support for it, until the list is changed. Q-R4 in [OPEN-QUESTIONS.md](../../OPEN-QUESTIONS.md) watches issue 313.
- The condition text names every host, so a second such host changes the text, not the severity; it is not notified again before its reminder.

## Revisit when

- smartmontools supports `mpi3mr` (issue 313), or a source shows another driver whose drives cannot be queried.
- A user reports a warning for a driver whose drives smartctl does read.
