# ADR 0034: Manual entries for the other pass-through types

- Status: Proposed
- Date: 2026-10-17
- Extends: [ADR 0005](0005-drive-discovery-and-identity.md), [ADR 0028](0028-logical-volumes-and-enclosures.md), [ADR 0029](0029-notification-field-device-id.md)

## Context

The drives behind the controllers that the device scan does not list, other than MegaRAID and HPE Smart Array, are reached only through manual entries in `[[discovery.device]]` (FR-104, [Research 04](../research/04-hardware-raid.md)). Milestone M6 asks for manual entries "for all other pass-through types" and for scenarios that show them.

What smartctl(8) of smartmontools 7.4 and 7.5 documents for Linux (the manual source `smartctl.8.in` of the tags `RELEASE_7_4` and `RELEASE_7_5`, read on 2026-10-17; the two versions do not differ for these types):

| Type | Controller | Node of the Linux examples | What the numbers are |
| --- | --- | --- | --- |
| `3ware,N` | 3ware, ATA disks | `/dev/twa0`, `/dev/twl0`, `/dev/twe0`; the deprecated form `/dev/sda` | `N`, 0 to 127, the disk on the controller |
| `areca,N` | Areca SATA RAID | `/dev/sg2` | `N`, 1 to 24, the disk on the controller |
| `areca,N/E` | Areca SAS RAID | as above | `N`, 1 to 128, the channel (slot), and `E`, 1 to 8, the enclosure |
| `aacraid,H,L,ID` | Adaptec (AacRaid) | `/dev/sda`; `scsi+aacraid,…` switches the implicit SAT off | host number, LUN and ID |
| `hpt,L/M` and `hpt,L/M/N` | HighPoint RocketRAID, ATA disks | `/dev/sda`, "the device node which stands for the disks derived from the HighPoint RocketRAID controllers" | controller, channel and PMPort |
| `sssraid,E,S` | SSSRAID, new and experimental in 7.4 | `/dev/bsg/sssraid0` | enclosure and slot |
| `jmb39x,N`, `jmb39x-q,N`, `jmb39x-q2,N`, `jms56x,N` | JMicron RAID port multiplier and USB bridge | not named | the port |

The validation of the configuration already accepted every one of these forms. The scenarios of M6, slice 6, showed three gaps:

1. **The node is taken for the drive.** For `aacraid`, `hpt` and the old form of `3ware` the node is a block device of the host, which is the logical volume of the controller. Discovery took the location, the ZFS pool, md array and volume group, and the inquiry data that lsblk shows for that node as the drive's, as it does for a drive read directly. A drive behind a controller whose logical volume has inquiry data of a known logical volume was even skipped as a logical volume instead of being monitored. [ADR 0028](0028-logical-volumes-and-enclosures.md) had already decided for MegaRAID that what lsblk shows for the node does not describe a drive behind it.
2. **The JMicron types write to the drive.** smartctl(8) says of `jmb39x` and `jms56x`: "The ATA pass-through commands are issued via READ/WRITE commands to a LBA of the RAID volume", and "Original sector data is not written back if smartctl is aborted with a signal". The tool stops smartctl after its timeout (FR-202). A manual entry of such a type breaks the rule that drives are only read ([ADR 0012](0012-read-only-and-coexistence-with-smartd.md)).
3. **No device ID and no controller location.** A drive read through `megaraid,N` or `cciss,N` has the location `<node> (<driver>), device N` and the notification field `device-id` ([ADR 0029](0029-notification-field-device-id.md)). The types above have neither. ADR 0029 names this under "Revisit when": "Another pass-through type, such as `cciss,N` or `areca,N`, is added: it gets the field in the same way." The decision itself defines the field as "the decimal number `N` as smartctl's type writes it", which fits `3ware,N` and `areca,N`, but not `areca,N/E`, `aacraid,H,L,ID`, `hpt,L/M/N` or `sssraid,E,S`, whose numbers are several. No recording of any of these controllers exists (Research 08).

The maintainer could not be asked; this record was written in an unattended session and takes, for each point, the option that changes no existing interface.

## Options considered

For the third point:

1. **No `device-id` and no controller location for these types in version 1.** The line `Drive:` of a message and the line of `scan` already name node and type, such as `/dev/sdb [aacraid,0,0,2]`, which is how smartctl addresses the drive. No notification gains a field.
2. **`device-id` for the types with one number** (`3ware,N`, `areca,N`), as ADR 0029 defines it, and nothing for the others. The field would mean the same as for MegaRAID, but for `areca` it would depend on the form of the type, `areca,2` against `areca,2/1`.
3. **`device-id` with every number of the type**, such as `0,0,2` for `aacraid,0,0,2` and `2/1` for `areca,2/1`. Tells all drives on one node apart, but changes what the field holds from a decimal number to a string of a form that differs per controller, which a `match-field` rule on it would have to know.

## Decision

1. **A type that reads a drive behind a controller does not take what the host shows for its node.** Besides `megaraid` and `cciss`, these are `3ware`, `areca`, `aacraid`, `hpt` and `sssraid`, also with `sat+` or `scsi+` before them. For such a drive, discovery takes no location, no membership and no inquiry data from lsblk, and the inquiry data of the node never make it a logical volume. Only `megaraid` and `cciss` have a controller location and a device ID, as before. This applies ADR 0028 to the other controllers and is a correction of discovery, not a change of an interface.
2. **A manual entry whose type is `jmb39x`, `jmb39x-q`, `jmb39x-q2` or `jms56x`, in any position of the type, is a configuration error** that says smartctl reads it by writing to a sector of the drive. Like every invalid configuration it does not stop a run: the last good configuration is used and `tool.config_invalid` is reported (ADR 0011). This follows from ADR 0012.
3. **Option 1 for the device ID and the controller location.** These types get neither the field `device-id` nor the line `Location:` in version 1. `device-id` stays what ADR 0029 decided: present for `megaraid,N`, `sat+megaraid,N` and the `cciss,N` forms, absent for every other drive.

## Consequences

- A drive behind an Adaptec or HighPoint controller no longer shows the ZFS pool, volume group or location of the logical volume it is read through, and is no longer skipped because that volume looks like one. Its pool is not shown at all, because the tool cannot tell which pool a drive behind the controller belongs to.
- A drive in JBOD or HBA mode that is also a block device of the host is kept as the block device, as for MegaRAID (FR-106), because the path through the controller no longer counts as a block device.
- A matcher cannot select one of several drives behind such a controller by a field other than `serial` and `model`. The text of every message names node and type.
- A configuration with a JMicron type, which no release has accepted, is refused.
- The scenario `manual-pass-through` of `tests/scenarios.py` shows one derived drive behind each of `areca` (both forms), `3ware`, `aacraid`, `hpt` and `sssraid`. Nothing of it is recorded: the label of these controllers in [docs/hardware-support.md](../hardware-support.md) is "Experimental".

## Revisit when

- A user contributes a recording of one of these controllers, which also shows what smartctl writes into the device fields of such a read.
- A user needs to select one drive behind such a controller in a matcher: options 2 and 3 above are then decided with the recording at hand.
