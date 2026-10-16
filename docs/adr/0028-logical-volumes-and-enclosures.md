# ADR 0028: Recognize logical volumes and enclosures by structured fields first

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR 0005](0005-drive-discovery-and-identity.md)

## Context

[ADR 0005](0005-drive-discovery-and-identity.md) says that discovery skips logical volumes of RAID controllers and devices that are not disks, decided from the smartctl output and the transport and not from the name (FR-107). It does not say how.
Since milestone M6 parses SCSI drives, a logical volume that smartctl reads without an error counts as a monitored drive; the Intel RAID volume of [Research 08](../research/08-public-recordings.md) is one.

What the host and smartctl tell about a logical volume of a MegaRAID controller (Research 08, source code of smartmontools 7.4 and 7.5):

- `lsblk` lists it as a disk with the vendor and the model of its inquiry data, which name the controller, not a drive.
- The device scan with `--scan-open` lists it as `scsi`. It opens it without a type, reads the inquiry data, and for the vendor `DELL` with a product `PERC…`, the vendor `MegaRAID`, a product beginning with `PERC `, or the vendor `LSI` it gives up with "DELL or MegaRaid controller, please try adding '-d megaraid,N'", which the scan writes to `devices[].open_error` (`os_linux.cpp` lines 2648–2652, `smartctl.cpp` line 1557 in 7.4 and 1561 in 7.5). The wording is the same in both versions.
- The tool reads every device with its type, here `--device=scsi`. With a type given, smartctl skips that inquiry check (`os_linux.cpp` lines 2600–2605 in both versions), so the drive output of a logical volume carries no message, only its inquiry data: `scsi_vendor`, `scsi_product`, `device_type`.

An enclosure answers through the controller like a drive (`megaraid,N`), and smartd has been seen mailing about one every day (Research 04). Its drive output has the SCSI peripheral device type 13; 12 is a storage array controller.

No recording of a MegaRAID logical volume, of an enclosure, or of a SAS drive read as `megaraid,N` is public (Research 08).

## Options considered

1. **The message of smartctl only.** One string, present only in the scan, and written for people: a new version of smartmontools can reword it, and the signal is gone without an error.
2. **The name** (`/dev/sda` next to `/dev/bus/N`). Says nothing: in JBOD mode the drives of the controller are block devices as well.
3. **Structured fields first, the message second.** The inquiry data of the block device and of the drive output, and the peripheral device type, are fields of their own in `lsblk` and in the JSON of smartctl; the message is an additional signal where those fields are missing.

## Decision

Option 3.

A device is skipped as `logical-volume` when one of these holds. Signals 1 and 3 are checked before the device is read, so that a volume they name is not read at all, and signal 2 after; the detail names the signal that decided:

1. **Before it is read:** its vendor and model in `lsblk` name a logical volume of a RAID controller.
2. **After it is read:** `scsi_vendor` and `scsi_product` of its output, or `vendor` and `product` of smartmontools 7.0 to 7.2, name one.
3. **Second signal:** its entry in the scan has an `open_error` that asks for `-d megaraid,N`. It is matched by the part `-d megaraid,N`, not by the whole sentence.

Vendor and product name a logical volume when, trimmed and compared without case:

- the vendor is `DELL` and the product begins with `PERC`, the product begins with `PERC `, the vendor is `MegaRAID`, or the vendor is `LSI`: the inquiry data that smartctl itself takes for a MegaRAID controller;
- the vendor is `Intel` and the product is `Raid` followed by a level and `Volume`: the Intel RAID volume of Research 08.

The list is kept in one place in the code and grows with recordings.

A device read as SCSI whose peripheral device type is neither 0 (disk) nor 14 (simplified direct-access disk) is skipped as `not-a-disk`, with the type in the detail: 13 an enclosure, 12 a storage array controller.

A drive behind the controller, read as `megaraid,N` or `sat+megaraid,N` on `/dev/bus/H`, has as its location the controller `/dev/bus/H` with the driver of SCSI host H from `/sys/class/scsi_host/hostH/proc_name`, and the device ID N. Both are shown in `scan` and in notifications and are never part of the identity ([ADR 0005](0005-drive-discovery-and-identity.md)).

## Consequences

- A logical volume is recognized whether or not smartctl can open it in the scan, and without depending on the wording of a message.
- **The message is fragile.** If a later smartmontools rewords it or stops writing `open_error`, the third signal falls away silently. The tests hold the wording of 7.4 and 7.5. A volume whose vendor and product are not on the list is then caught by nothing: it is read and counted as a drive, usually without SMART data. `pve-smart-alert scan` shows it, which is the safeguard ADR 0005 names, and an exclude rule removes it.
- The vendor `LSI` is broader than the check of smartctl, which compares four bytes `LSI` and NUL. A drive whose vendor field is `LSI` is not known; such a drive would be skipped (**Assumed**, Q-R1).
- Physical drives in JBOD mode keep the inquiry data of the drive, so they are not taken for volumes; they are kept once by the de-duplication of ADR 0005.
- Reading the driver of a SCSI host from sysfs is shared with the detection of controllers that cannot be queried (milestone M6, slice 4).

## Revisit when

- A recording of a MegaRAID logical volume or enclosure shows other inquiry data or another type.
- smartmontools rewords the message or changes how `open_error` is written.
- Another controller family is added whose volumes need a pattern of their own, such as the logical drives of HPE Smart Array.
