# ADR 0029: The notification field `device-id` for drives behind a controller

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR 0008](0008-notification-integration.md), [ADR 0028](0028-logical-volumes-and-enclosures.md)

## Context

A notification about a single drive carries the metadata fields `event`, `device`, `serial` and `model` besides `type` and `hostname` (FR-502, FR-503). Matchers of the Proxmox VE notification system select notifications by these fields, and webhook bodies use them.

A drive behind a MegaRAID controller is read as `megaraid,N` or `sat+megaraid,N` on the node `/dev/bus/H` ([ADR 0028](0028-logical-volumes-and-enclosures.md)). Every drive behind one controller has the same `device`, so a matcher on `device` cannot tell them apart. The device ID `N` is in the text of the message (`Location: /dev/bus/6 (megaraid_sas), device 8`), but not in a field.

The field names are a stable interface (NFR-21): changing what `device` holds would change which notifications an existing matcher selects.

What the notification system does with fields ([Research 01](../research/01-notification-integration.md)): a `match-field` rule on a field the notification does not have does not match. The server accepts any field name that is a valid identifier, and its own field `job-id` has a hyphen.

The maintainer decided the question (Q-N10) on 2026-10-16.

## Options considered

1. **The device ID in `device`**, such as `/dev/bus/6 [megaraid,8]`. Breaks NFR-21: an existing rule `exact:device=/dev/bus/6` would stop matching.
2. **No new field.** The drives differ in `serial` and `model`, which select one drive. Nothing selects the drive in one position of the controller, whatever drive sits there.
3. **A new field `device-id`**, only for drives read through a pass-through type.

## Decision

Option 3.

- The field `device-id` holds the device ID of the pass-through type of the read, the decimal number `N` as smartctl's type writes it: `8` for `megaraid,8`, `14` for `sat+megaraid,14`. Not the whole type: the type is a detail of how smartctl reads the drive, the ID is where the drive sits, and `device` already names the controller.
- It is present in a notification about a single drive read through `megaraid,N` or `sat+megaraid,N`. `cciss,N` follows with the HPE probe of milestone M6, slice 5.
- It is absent, not empty, for every other drive and for every notification that is not about one drive: the summary, the first-run summary, a message about the tool and the test notification. An empty value would match `regex:device-id=.*` and `exact:device-id=` and so tell a matcher something that is not there; an absent field matches no rule.
- For a missing drive it is the device ID of the last read, which the state keeps with the device type.
- `device` stays as it is.
- One function in the model reads the device ID from the device type. The location that `scan` and the message show, and the field, come from it, so that they cannot disagree.
- The routing check of [ADR 0020](0020-routing-check.md) counts `device-id` as a field that differs between the notifications of the tool: a rule on it is undecided, never "routed" or "not routed".

## Consequences

- A matcher can select one position of a controller, for example with `match-field exact:device=/dev/bus/6` and `match-field exact:device-id=8` in `mode all`.
- **The device ID can change.** A controller can give a drive another ID after a reboot, a firmware update or a rebuild; the tool keeps the drive by its identity ([ADR 0005](0005-drive-discovery-and-identity.md)), and the field follows the current read. A matcher that must follow one drive uses `serial`.
- The web interface does not offer the field, as for `serial` (Research 01): a rule on it is written in `/etc/pve/notifications.cfg` or through the API.
- `device-id` is a notification field under NFR-21 from now on.

## Revisit when

- Another pass-through type, such as `cciss,N` or `areca,N`, is added: it gets the field in the same way.
- A user needs the type of the read in a field as well.
