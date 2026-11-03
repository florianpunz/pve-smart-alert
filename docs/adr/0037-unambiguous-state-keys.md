# ADR 0037: Unambiguous keys in the state file

- Status: Superseded by [0038](0038-unambiguous-keys-of-devices-without-an-identity.md) for the access key of a device without an identity only; every other part of the record governs as before
- Date: 2026-11-01
- Decides: the key of a drive record in the state file and its migration

## Context

The state keeps one record per drive, keyed by the identity ([ADR 0005](0005-drive-discovery-and-identity.md), [ADR 0007](0007-state-storage.md)). Since the first schema the key was built by joining its parts with `|`:

- `<model>|<serial>`,
- `<model>|wwn:<wwn>` for a drive without a serial number,
- `<model>|device:<name>|<type>` for a drive without either.

A model or serial number is a string a drive reports. It can contain a `|`, and nothing prevents a serial number from starting with `wwn:`. Then two different drives produce the same key: model `A|B` with serial `C` and model `A` with serial `B|C` both key `A|B|C`. The planner stores the second record over the first, so the two drives share conditions, baselines and missing-drive detection: a notification can be suppressed, escalated or attributed to the wrong drive.

The security review of milestone M7 found this. It is unlikely with real hardware, but the consequence is a wrong notification about a drive, which is what the tool exists to prevent.

## Options considered

1. **Escape the separator in each part.** Keeps the readable shape of the file. Works, but every part has to be escaped and unescaped in the same way, in three places that build or read a key.
2. **Write the parts as a JSON array.** `json.dumps` escapes every character that would be ambiguous, and the same call produces the key everywhere. The key is longer and less readable in the file, which is engineering detail and not what a user reads.
3. **Keep the format and accept the collision.** Rejected: two drives sharing a record is a silent wrong result.

## Decision

Option 2.

- The key is the JSON array of its parts: `["ST6000NM0115-1YZ110", "serial", "ANON-SN-0001"]`, `["<model>", "wwn", "<wwn>"]`, and `["<model>", "device", "<name>|<type>"]` for a drive without a serial number and a WWN. No part can be split at a character another part contains.
- The access key inside the last form keeps its `|<type>` shape: a device name is validated against a strict pattern that does not allow `|` (FR-104), so it is unambiguous.
- The schema becomes version 2. Loading a version-1 file runs a migration that rebuilds each key from the record itself: the record carries the identity and the last access. A record that carries neither keeps its old key, so a damaged record is not lost by the migration.
- The migration runs on load, before anything compares keys, so a build upgrade finds every drive again: no false missing notification and no new record.
- The key is not part of the user interface; `status --json` shows it, and ADR 0007 already calls the state file engineering detail.

## Consequences

- Two drives can no longer share a state record, whatever their model and serial number contain.
- The state file of a version 0.5.0 host is migrated on its first run and written back in schema 2. A downgrade to a build that knows only schema 1 sets the file aside, as ADR 0007 describes for a newer schema.
- The records of a drive are no longer readable by eye as `model|serial`; `status` and the notifications show the drive, not the key.

## Revisit when

- A tool outside the project reads the keys of the state file, which no decision promises.
