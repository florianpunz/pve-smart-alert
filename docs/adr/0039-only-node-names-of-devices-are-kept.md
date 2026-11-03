# ADR 0039: Only the node names of devices are kept

- Status: Accepted
- Date: 2026-11-02
- Decided by: the maintainer
- Supersedes: the "device names are kept" part of [ADR 0023](0023-anonymization-of-recordings.md)

## Context

[ADR 0023](0023-anonymization-of-recordings.md) lists device names among the values that are not identifying and are kept. That holds for the node smartctl is called with, such as `/dev/sda` or `/dev/nvme0n1`.

The security review of milestone M7 found the exception: a manual entry may name a link under `/dev/disk/`, such as `/dev/disk/by-id/ata-<model>_<serial>`. Its name holds the serial number of the drive, and `dump-fixture` wrote that name into the file names of its archive, into `recording.json` and into every text.

A rule that replaces only names under `/dev/disk/` misses the other names that hold an identifier: a device-mapper name is the WWID when `user_friendly_names` is off, and a `/dev/serial/by-id/` link can hold a serial number. The fail-closed check does not help there, because it searches for values it has learned from a field of a drive, and an identifier that appears only in the name is never learned.

Replacing every device name would be wrong in the other direction. A re-recorded fixture would name `/dev/anon1` where the host has `/dev/bus/6` (MegaRAID), `/dev/bsg/sssraid0` (SSSRAID) or `/dev/nvme0n1`, and the replay in the tests and the hardware support document would no longer show the node the tool used.

A drive output can also take the name of another file of a fixture: a drive read through `/dev/scan` was written as `scan.json` and overwrote the device scan.

## Decision

- A device name is kept only when it has the shape of a node that names no drive: `/dev/sdX`, `/dev/nvmeXnY`, `/dev/sgN`, `/dev/bsg/<name><N>`, `/dev/bus/<N>`, `/dev/dm-N`, `/dev/cciss/cXdY`, `/dev/mdN` and the 3ware nodes `/dev/twaN`, `/dev/tweN` and `/dev/twlN`.
- Every other device name is replaced by `/dev/anonN` of this archive, in the file name, in `recording.json` and in every text of the recording alike. This covers a `by-id` link, a `by-path` link, a mapper name such as `/dev/mapper/<volume group>-<volume>` or a multipath WWID, a serial link and a named md array such as `/dev/md/<name>`. The volume group and pool of a drive stay in the membership that `lsblk` reports.
- The fail-closed check still searches every text, including a name that is kept, but it is not what protects a name: the whitelist above does.
- A drive output is named after the stem of its recording, so that a fixture keeps the file names its source gave it. When the device name was replaced, the anonymized name gives the file name instead of the stem.
- A drive whose file name would be `scan`, `lsblk` or `recording` gets a numbered name, such as `scan-2.json`, so that a fixture never loses one of its other files.

## Consequences

- A fixture names the nodes the tool read; every other device name appears as `/dev/anonN` and `anonN.json`, also when it held no identifier.
- A name that is kept cannot hold an identifier, because only the node shapes above are kept.
- The names of a fixture remain unique, and the scan, `lsblk` and the metadata are always present.

## Revisit when

- The tool starts to use a node shape that the whitelist does not name, so that its fixtures would anonymize a real node.
- A device name with a node shape is found to hold an identifier.
