# ADR 0026: Anonymize the names of SCSI drives, and import the test data of other projects

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR 0023](0023-anonymization-of-recordings.md)

## Context

Milestone M6 covers SAS drives and drives behind RAID controllers on recorded data ([ROADMAP.md](../../ROADMAP.md)).
The project has none of this hardware, so its first recordings come from the test data that other projects publish ([Research 08](../research/08-public-recordings.md)).
Two things are not decided yet.

First, [ADR 0023](0023-anonymization-of-recordings.md) lists the identifiers of ATA and NVMe drives and says that the list grows with the first recordings of SAS drives.
smartctl writes two more identifiers for a SCSI drive, both as text, `0x` and hexadecimal digits (Research 08):

- `logical_unit_id`, the name from the device identification page, in every output of a SCSI drive;
- `sas_address` and `attached_sas_address` of every phy, in `scsi_sas_port_N.phy_M`, only with `--xall`. The attached address is that of the controller or the expander, so it identifies the host.

The logical unit id of the recordings is an NAA name. Udev and `lsblk` write the WWN of the block device from the same identification page, so for a SAS drive the WWN in `lsblk` is expected to be the logical unit id (**Assumed**: no recording shows both).

Second, ADR 0023 lets only the anonymizer write fixtures, from archives of the collection script. A file of another project has no archive around it, often no device scan, sometimes values its project already replaced, and a license of its own.

## Options considered

For the names:

1. **Remove the fields.** Breaks the de-duplication tests of milestone M6, which need the names of two paths to one drive.
2. **A counter of their own.** A drive would then have one placeholder as logical unit id and another as WWN in `lsblk`, although both are the same name.
3. **The rules of ADR 0023 by the form of the name.** An NAA 5 name is a WWN (16 digits: authority, vendor, number) and gets the WWN placeholder; an NAA 6 name keeps its authority and vendor like a WWN; any other form becomes a counter.

For the import:

1. **Copy the files by hand and anonymize them by hand.** Contradicts ADR 0023.
2. **Wrap them into an archive of the collection script.** Would invent a scan, a node and exit statuses that the source does not have.
3. **An import mode of the same tool**, which reads the files where they are and records what is missing as missing.

## Decision

Option 3 for both.

Names:

- `logical_unit_id`, `sas_address` and `attached_sas_address` are identifiers wherever they occur in an output.
- An NAA 5 name of 16 digits shares the counter and the placeholder of the WWNs: `naa` and `oui` stay, `id` becomes the counter. The same name gets the same placeholder in the drive output and in `lsblk`.
- An NAA 6 name of 32 digits keeps its first 7 digits, authority and vendor, and the other 25 become a counter of NAA names.
- Any other name keeps its number of digits and becomes a counter of NAA names, written in hexadecimal.
- A name that is zero, such as the attached address of a phy that is attached to nothing, names nothing and stays.
- A value in one of these fields that is not `0x` and hexadecimal digits makes the anonymizer fail closed.
- The fixture test checks these fields like the others.

Import (`scripts/make_fixtures.py import`):

- Only data under a license compatible with AGPL-3.0-or-later is imported. The tool accepts exactly these SPDX identifiers and refuses any other: `MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `Apache-2.0`, `LGPL-2.1-or-later`, `LGPL-3.0-or-later`, `GPL-2.0-or-later`, `GPL-3.0-only`, `GPL-3.0-or-later` and `AGPL-3.0-or-later`.
- Not imported: output that is only quoted in an issue tracker or a forum, because its author granted no license, and data whose license was granted by someone else than the author of the output. Such output is cited as evidence in a research note.
- The files are read at a pinned commit of the source. `recording.json` records the repository, the commit, the path of every file, the copyright line and the license text, which is kept below `tests/fixtures/licenses/`. `THIRD-PARTY-NOTICES.md` and `debian/copyright` name every source.
- One fixture is made of the files that the source shows to belong together, usually one. A scan or a drive file that the source does not have is not made up: the fixture has no `scan.json`, or no drive files.
- What the source already changed, such as a serial number replaced by a word, is recorded in `source.changes`. Such a value is treated as real and anonymized like any other.
- A fixture is placed below the controller its drives are behind (ADR 0023); a drive that answers as a SCSI block device of unknown origin is placed below `direct`.

## Consequences

- A SAS drive keeps one placeholder for its name in every file of a recording, as an ATA drive does for its WWN.
- `pve-smart-alert dump-fixture` uses the same anonymizer, so archives contributed by users with SAS drives are anonymized by the same rules before they are offered for SAS ([ADR 0023](0023-anonymization-of-recordings.md)).
- The scenario tests and the fake smartctl need a scan. A scenario on an imported drive without one derives its scan, and is marked as derived ([ADR 0016](0016-test-strategy.md)).
- Recordings taken from other projects come without their context: the host, the controller and sometimes the version of smartmontools are unknown. Their evidence level is "Verified by fixtures" only for what the file itself shows.
- A source that redacted values by its own rules can make two drives look like one. `source.changes` says so, and a test that needs two distinct drives derives them.

## Revisit when

- A recording shows a SAS address or a logical unit id in a form not covered here.
- A recording shows the WWN of a SAS drive in `lsblk` that differs from its logical unit id.
- A source changes its license.
