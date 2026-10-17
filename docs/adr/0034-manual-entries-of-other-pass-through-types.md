# ADR 0034: Drives behind the other RAID controllers

- Status: Proposed
- Date: 2026-10-17
- Extends: [ADR 0005](0005-drive-discovery-and-identity.md), [ADR 0012](0012-read-only-and-coexistence-with-smartd.md), [ADR 0028](0028-logical-volumes-and-enclosures.md), [ADR 0029](0029-notification-field-device-id.md), [ADR 0032](0032-hpe-smart-array-probe.md)

## Context

Besides MegaRAID and HPE Smart Array, smartctl reaches the drives behind several other RAID controllers with types of their own ([Research 04](../research/04-hardware-raid.md), with its addition of 2026-10-17). Milestone M6 asks for these "manual device entries for all other pass-through types" and for scenarios that show them.

What smartctl(8) of smartmontools 7.4 and 7.5 documents for Linux (the manual source `smartctl.8.in` of the tags `RELEASE_7_4` and `RELEASE_7_5`, read on 2026-10-17), and what the source `os_linux.cpp` of both versions does in the scan:

| Type | Controller | Node of the Linux examples | What the numbers are | Listed by the scan |
| --- | --- | --- | --- | --- |
| `3ware,N` | 3ware, ATA disks | `/dev/twa0`, `/dev/twl0`, `/dev/twe0`; the deprecated form `/dev/sda` | `N`, 0 to 127, the disk on the controller | No |
| `areca,N` | Areca SATA RAID | `/dev/sg2` | `N`, 1 to 24, the disk on the controller | No |
| `areca,N/E` | Areca SAS RAID, SATA or SAS disks | none for Linux; the tool accepts it on `/dev/sgN` as `areca,N` | `N`, 1 to 128, the channel (slot), and `E`, 1 to 8, the enclosure | No |
| `aacraid,H,L,ID` | Adaptec (AacRaid), SATA or SAS disks | `/dev/sda`; `scsi+aacraid,…` switches the implicit SAT off | host number, LUN and ID | No |
| `hpt,L/M` and `hpt,L/M/N` | HighPoint RocketRAID, ATA disks | `/dev/sda`, "the device node which stands for the disks derived from the HighPoint RocketRAID controllers" | controller, channel and PMPort | No |
| `sssraid,E,S` | SSSRAID, SATA or SAS disks, new and experimental in 7.4 | `/dev/bsg/sssraid0` | enclosure and slot | Yes: `get_dev_sssraid` lists the drives of every SCSI host with the driver `sssraid` |
| `jmb39x,N`, `jmb39x-q,N`, `jms56x,N`, and in 7.5 also `jmb39x-q2,N` | JMicron RAID port multiplier and USB bridge | not named | the port | No |

The validation of the configuration already accepted every one of these forms. smartctl also takes `scsi+` and `sat` with its options, such as `sat,auto+`, before a controller type (`dev_interface.cpp` of 7.5). The scenarios of M6, slice 6, and their review showed four gaps:

1. **The node is taken for the drive.** For `aacraid`, `hpt` and the old form of `3ware` the node is a block device of the host, which is the logical volume of the controller. Discovery took the location, the ZFS pool, md array and volume group, and the inquiry data that lsblk shows for that node as the drive's, as it does for a drive read directly. A drive behind a controller whose logical volume has inquiry data of a known logical volume was even skipped as a logical volume instead of being monitored. [ADR 0028](0028-logical-volumes-and-enclosures.md) had already decided for MegaRAID that what lsblk shows for the node does not describe a drive behind it.
2. **The JMicron types write to the drive.** smartctl(8) says of `jmb39x` and `jms56x`: "The ATA pass-through commands are issued via READ/WRITE commands to a LBA of the RAID volume", and "Original sector data is not written back if smartctl is aborted with a signal". The tool stops smartctl after its timeout (FR-202). A manual entry of such a type breaks the rule that drives are only read ([ADR 0012](0012-read-only-and-coexistence-with-smartd.md)).
3. **A SATA drive behind these controllers can be woken.** The tool passes `--nocheck=standby` for the ATA and SAT types and, by [ADR 0032](0032-hpe-smart-array-probe.md), for every `cciss` form, but not for the types above. Behind 3ware, Areca and HighPoint the drives are ATA or SATA drives, and behind Adaptec and SSSRAID they can be, so every run could wake such a drive in standby (FR-203).
4. **No device ID and no controller location.** A drive read through `megaraid,N` or `cciss,N` has the location `<node> (<driver>), device N` and the notification field `device-id` ([ADR 0029](0029-notification-field-device-id.md)). The types above have neither. ADR 0029 names this under "Revisit when": "Another pass-through type, such as `cciss,N` or `areca,N`, is added: it gets the field in the same way", and ADR 0032 gives `cciss,N` the field "as ADR 0029 says for every pass-through type". The decision of ADR 0029 defines the field as "the decimal number `N` as smartctl's type writes it", which fits `3ware,N` and `areca,N`, but not `areca,N/E`, `aacraid,H,L,ID`, `hpt,L/M/N` or `sssraid,E,S`, whose numbers are several. The project has no recording of any of these controllers.

The maintainer was not available for this decision. For each point it takes the option that keeps every key, field, check identifier and command as it is.

## Options considered

For the fourth point:

1. **No `device-id` and no controller location for these types in version 1.** The line `Drive:` of a message and the line of `scan` already name node and type, such as `/dev/sdc [aacraid,0,0,2]`, which is how smartctl addresses the drive. No notification gains a field.
2. **`device-id` for the types with one number** (`3ware,N`, `areca,N`), as ADR 0029 defines it, and nothing for the others. The field would mean the same as for MegaRAID, but for `areca` it would depend on the form of the type, `areca,2` against `areca,2/1`.
3. **`device-id` with every number of the type**, such as `0,0,2` for `aacraid,0,0,2` and `2/1` for `areca,2/1`. Tells all drives on one node apart, but changes what the field holds from a decimal number to a string of a form that differs per controller, which a `match-field` rule on it would have to know.

## Decision

1. **A type that reads a drive behind a controller does not take what the host shows for its node.** These are `megaraid`, `cciss`, `3ware`, `areca`, `aacraid`, `hpt` and `sssraid`, also with `scsi+` or `sat` and its options before them. For such a drive, discovery takes no location, no membership and no inquiry data from lsblk, and the inquiry data of the node never make it a logical volume. Only `megaraid` and `cciss` have a controller location and a device ID, as before. This applies ADR 0028 to the other controllers.
2. **A type that smartctl reads by writing to the drive never reaches smartctl.** These are `jmb39x`, `jmb39x-q`, `jmb39x-q2` and `jms56x`, in any position of the type. In `[[discovery.device]]` such a type is a configuration error that says so; like every invalid configuration it does not stop a run, the last good configuration is used and `tool.config_invalid` is reported (ADR 0011). A last good configuration that an earlier build saved with such an entry drops the entry, and a device of any source with such a type is not read. This follows from ADR 0012 and narrows the values that the key `discovery.device.type` accepts; the key itself is unchanged.
3. **A drive behind 3ware, Areca, Adaptec, HighPoint or SSSRAID gets the standby check whatever its protocol says**, as every `cciss` form does by ADR 0032: smartctl is called with `--nocheck=standby`, and a drive in standby keeps its previous state (FR-203). smartctl implements the power mode check for ATA and SCSI alike (ADR 0032), so a SAS drive behind such a controller is read as before unless it is in standby.
4. **Option 1 for the device ID and the controller location.** These types get neither the field `device-id` nor the line `Location:` in version 1. `device-id` stays what ADR 0029 decided: present for `megaraid,N`, `sat+megaraid,N`, `scsi+megaraid,N` and the `cciss,N` forms, absent for every other drive. This departs from the intention that ADR 0029 states under "Revisit when" and that ADR 0032 repeats, "for every pass-through type"; it changes neither decision for the types they cover.

## Consequences

- A drive behind an Adaptec or HighPoint controller no longer shows the ZFS pool, volume group or location of the logical volume it is read through, and is no longer skipped because that volume looks like one. Its pool is not shown at all, because the tool cannot tell which pool a drive behind the controller belongs to.
- A drive in JBOD or HBA mode that is also a block device of the host is kept as the block device, as for MegaRAID (FR-106), because the path through the controller no longer counts as a block device.
- A SATA drive behind these controllers is no longer woken by a run; one in standby is shown as in standby.
- A matcher cannot select one of several drives behind such a controller by a field other than `serial` and `model`. FR-507 asks for location information "controller and device ID, or bus path"; for these drives the message gives node and type in the line `Drive:` and no line `Location:`. Whether that is enough is part of this proposal.
- A configuration with a JMicron type, which no release has accepted, is refused, and the development builds that saved one as the last good configuration no longer read it.
- smartctl itself creates the device nodes it needs for some of these controllers, outside the files of the tool: `/dev/aacH` for `aacraid`, the nodes `/dev/twaN`, `/dev/twlN` and `/dev/tweN` for `3ware`, which it also recreates when they have the wrong numbers, and the ioctl node of a MegaRAID controller, which already happens in the scan (`os_linux.cpp` of 7.5). The tool does not do this and cannot prevent it; ADR 0012 limits what the tool changes, and the call of smartctl that an administrator configures brings this with it.
- The scenario `manual-pass-through` of `tests/scenarios.py` shows one derived drive behind each of `areca` (both forms), `3ware`, `aacraid`, `hpt` and `sssraid`, the last one from the scan. Nothing of it is recorded: the label of these controllers in [docs/hardware-support.md](../hardware-support.md) is "Experimental", and what smartctl writes into their device fields is Q-R9.

## Revisit when

- A user contributes a recording of one of these controllers, which also shows what smartctl writes into the device fields of such a read.
- A user needs to select one drive behind such a controller in a matcher: options 2 and 3 above are then decided with the recording at hand.
