# ADR 0039: A device name under /dev/disk is identifying

- Status: Accepted
- Date: 2026-11-02
- Decided by: the maintainer
- Supersedes: the "device names are kept" part of [ADR 0023](0023-anonymization-of-recordings.md)

## Context

[ADR 0023](0023-anonymization-of-recordings.md) lists device names among the values that are not identifying and are kept. That holds for the node smartctl is called with, such as `/dev/sda` or `/dev/nvme0n1`.

The security review of milestone M7 found the exception: a manual entry may name a link under `/dev/disk/`, such as `/dev/disk/by-id/ata-<model>_<serial>`. Its name holds the serial number of the drive, and `dump-fixture` wrote that name into the file names of its archive, into `recording.json` and into every text.

Replacing every device name would be wrong in the other direction. A re-recorded fixture would name `/dev/anon1` where the host has `/dev/bus/6` (MegaRAID), `/dev/bsg/sssraid0` (SSSRAID) or `/dev/nvme0n1`, and the replay in the tests and the hardware support document would no longer show the node the tool used.

A device name can also take the name of another file of a fixture: a drive read through `/dev/scan` was written as `scan.json` and overwrote the device scan.

## Decision

- A device name under `/dev/disk/` is replaced by `/dev/anonN` of this archive, in the file name, in `recording.json` and in every text of the recording alike.
- Every other device name is kept, such as `/dev/sda`, `/dev/nvme0n1`, `/dev/bus/6`, `/dev/bsg/sssraid0`, `/dev/dm-0` or `/dev/mapper/<volume group>-<volume>`.
- The fail-closed check searches a kept name for every learned value like any other text, so a real value in a name that is kept aborts the archive.
- A drive whose file name would be `scan`, `lsblk` or `recording` gets a numbered name, such as `scan-2.json`, so that a fixture never loses one of its other files.

## Consequences

- A fixture names the nodes the tool read, and a `by-id` link appears as `/dev/anonN` and `anonN.json`.
- The names of a fixture remain unique and the scan, `lsblk` and the metadata are always present.
- A device name outside `/dev/disk/` that holds an identifier is caught by the fail-closed check instead of being replaced.

## Revisit when

- A device name outside `/dev/disk/` is found to hold an identifier that the fail-closed check cannot see.
