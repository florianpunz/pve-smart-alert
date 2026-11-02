# ADR 0038: Records of a device without an identity are keyed unambiguously too

- Status: Accepted
- Date: 2026-11-02
- Decided by: the maintainer
- Supersedes: the access-key bullet of [ADR 0037](0037-unambiguous-state-keys.md)

## Context

[ADR 0037](0037-unambiguous-state-keys.md) writes the key of a drive record as a JSON array, but keeps the access key of a device without an identity as `<name>|<type>`. It argues that a device name is validated against a strict pattern that does not allow `|` (FR-104).

That argument does not hold on the path of the device scan that fails its check: discovery keeps a record for such a device as well, and that record only ever holds the condition `drive.unreadable` (ARCHITECTURE.md section 9). Name and type are then strings that the scan reported, and the scan is untrusted data. The collision ADR 0037 removes for the model and the serial number survives there: two such devices can share one record, so one unreadable device hides the other.

The security review of milestone M7 found this.

## Decision

Option: the access key becomes a JSON array as well.

- The access key is the JSON array of name and type, `["<name>", "<type>"]`.
- A record of a device without an identity is stored under `device:` followed by that array, such as `device:["/dev/sda", "sat"]`.
- A drive without a serial number and a WWN is keyed `["<model>", "device", "<name>", "<type>"]`.
- The schema-2 migration re-keys a schema-1 record without an identity from its last access as well. A record without a usable last access is rejected by the validation after the migration, so the whole file is set aside as [ADR 0007](0007-state-storage.md) describes; the migration's fallback is not reached end to end.
- `status` reads the old `name|type` key of a skipped device in a state that 0.5.0 wrote, until the next run rewrites the entry.

## Consequences

- No two records of the state file can share a key, whatever the device scan reported.
- A state of schema 1 is migrated for every record, whether the device answered with an identity or not.
- The skipped devices of a state written by 0.5.0 keep the old key until the next run; `status` shows both forms.

## Revisit when

- A tool outside the project reads the keys of the state file, which no decision promises.
