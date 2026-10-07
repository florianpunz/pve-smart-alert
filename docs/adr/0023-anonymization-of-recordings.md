# ADR 0023: Anonymize recordings with counters per archive

- Status: Accepted
- Date: 2026-10-07
- Decided by: the maintainer, for the form of the placeholders

## Context

[ADR 0016](0016-test-strategy.md) requires that no fixture carries a real serial number or WWN, that identifying values are replaced by stable placeholders, and that a test enforces this. It leaves open which values identify a drive and what replaces them.
`pve-smart-alert dump-fixture` (FR-604, NFR-14) applies the same rules on the hosts of users, so the rules are part of what the tool promises.

The recordings of the test cluster ([Research 06](../research/06-test-cluster-recordings.md)) were searched for every serial number, WWN and EUI-64 of their drives, in every form, in every file of an archive of [`scripts/collect-node-data.sh`](../../scripts/collect-node-data.sh). The values occur here:

| File | Fields | Form |
| --- | --- | --- |
| Drive output of smartctl, ATA | `serial_number`; `wwn` with `naa`, `oui`, `id` | String; numbers, of which `id` is the part that identifies |
| Drive output of smartctl, NVMe | `serial_number`; `nvme_namespaces[].eui64` with `oui`, `ext_id` | String; numbers, of which `ext_id` is the part that identifies |
| Device scan of smartctl | None | – |
| `lsblk -J -O` | `serial`, `wwn`, `id`, `id-link`; `uuid`, `partuuid`, `ptuuid` | Strings: the WWN or EUI-64 as 16 hexadecimal digits, the serial number inside the udev name and the `by-id` link |
| Disk list of the web interface | `serial`, `wwn`, `by_id_link` | Strings, as in `lsblk` |
| `pvs` | `pv_uuid` | String |

Not identifying, and kept: model, firmware version, capacities, the OUI of a vendor, PCI vendor IDs, SMART values, device names, node names, the names of volume groups, the time of the recording.
smartctl writes no NGUID into its JSON output (smartmontools source, `nvmeprint.cpp`); an NGUID can appear only in the output of `lsblk` and in udev names. The Fanxiang S301 reports a WWN with the `id` 89, a value that cannot be unique; it is treated like any other WWN.

## Options considered

1. **A hash of each value.** Stable, but a serial number has a known format and few possible values, so a hash can be reversed by trying them.
2. **Random placeholders.** Not reversible, but a reader cannot tell two placeholders apart from two real values at a glance, and stability needs the same mapping table anyway.
3. **Counters per archive, in the order of the scan.** Not reversible, readable, and the same real value gets the same placeholder in every file of an archive.
4. **Removing the fields.** Breaks every test of identity and de-duplication.

## Decision

Option 3, with these forms:

- A counter per kind of identifier and per archive, starting at 1. Values are numbered in the order of the device scan, then the devices that the scan does not list, by file name. The same real value gets the same placeholder in every file of the archive.
- Serial number: `ANON-SN-0001`, `ANON-SN-0002`, and so on.
- WWN: `naa` and `oui` stay, `id` becomes the counter. Where the WWN is written as 16 hexadecimal digits, the digits of the anonymized WWN replace it.
- EUI-64: `oui` stays, `ext_id` becomes the counter, and its hexadecimal form is replaced alike.
- NGUID and every other unique identifier: the vendor part stays and the rest becomes the counter. An identifier without a vendor part, such as a UUID, becomes the counter in its own notation, `00000000-0000-0000-0000-000000000001`.
- The anonymizer fails closed: after it has replaced the values, it searches every output for every real value in each of its forms, and a single hit aborts without writing anything.
- Fixtures are written only by the anonymizer, through [`scripts/make_fixtures.py`](../../scripts/make_fixtures.py), never by hand. The JSON keeps its content and is written indented.
- Layout of recorded fixtures: `tests/fixtures/smartctl/<controller>/<recording>/` with `scan.json`, one file per device named after the device, and `recording.json` with origin, license, smartmontools version and the command line and exit status of every file. Directly attached drives have the controller `direct`. This fills in the location rule of ADR 0016.
- A test reads every fixture and fails when a field known to hold an identifier holds anything but a placeholder.
- This milestone applies the rules to the device scan and the drive output of smartctl. The other files of an archive follow the same rules when they become fixtures, starting with `lsblk` for the enrichment of discovery.

## Consequences

- No fixture can be traced to a drive, and reviewing an anonymized file shows at a glance which values were replaced.
- The counters start again in every archive. Two recordings both have `ANON-SN-0001`, so a scenario that combines drives of two recordings has to renumber them and is marked as derived ([ADR 0016](0016-test-strategy.md)).
- A placeholder shows how many drives a host has and in which order the scan lists them. That is not identifying.
- A value that is too short to search for safely, such as a serial number of fewer than four characters, is replaced only in its own field. Such a value carries no identity anyway.
- SAS drives, the FARM log of Seagate drives and drives behind RAID controllers carry identifiers that no recording shows yet, such as SAS addresses. The list grows with their first recordings in milestone M6, before `dump-fixture` is offered for them.

## Revisit when

- A recording shows an identifier that is not on the list.
- smartmontools adds an identifier to its JSON output, such as the NGUID.
