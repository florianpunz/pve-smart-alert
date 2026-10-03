# ADR 0009: Notification policy: once, on worsening, and on reminder

- Status: Accepted
- Date: 2026-10-03

## Context

The maintainer's goal: no alert flood. A problem is reported once and again only when it gets worse or after a configurable interval.
The counter-example is smartd on Debian, which repeats its mail every day for as long as a problem exists ([Research 02](../research/02-builtin-smart-handling.md)).

Situations the policy has to handle without a flood:

- The first run on a host whose drives already have history.
- A value that sits exactly on a threshold and flips on every run, typically temperature.
- A counter that increases on every run while a drive is dying.
- One cause that affects many drives at once: a failed fan, a backplane, a power supply.
- A cumulative counter with an old non-zero value, typically CRC errors.
- A drive that disappears because it died, was replaced, or was a USB disk.
- The notification system being unavailable for a while.

## Options considered for granularity

1. **One notification per finding.** A dying drive usually trips several checks at once. This multiplies messages for one incident.
2. **One notification per run** (digest). Flood-proof by construction. But a notification about one drive cannot carry drive metadata for webhooks, and unrelated incidents share one message.
3. **One notification per drive, collapsing to one summary above a limit.** One message per incident in the normal case, bounded in the mass case.

## Decision

### Two kinds of findings

- A **condition** is a state that holds or does not hold: "17 reallocated sectors", "wear at 96 %", "health check failed". It is active until it clears. Reminders and recovery apply.
- An **event** is an increase of a cumulative counter since the stored baseline: "CRC errors rose from 12 to 19". It is reported and the baseline moves. There is no active state, no reminder and no recovery.

Which check is of which kind is fixed in the check catalog ([ADR 0010](0010-health-evaluation-and-default-thresholds.md)).

### When a condition is notified

| Situation | Notification | Timing |
| --- | --- | --- |
| Condition appears | Yes, event `problem` | After the confirmation count of the check, by default at once |
| Severity rises | Yes, event `escalated` | At once, ignores the cool-down |
| Value worsens at the same severity, for checks that track worsening | Yes, event `worsened` | Only if the cool-down since the last notification for this drive has passed (default 6 hours) |
| Nothing changed and the reminder interval has passed | Yes, event `reminder` | Per severity: critical 3 days, warning 7 days, notice never |
| Severity falls | No | The lower severity is used from then on |
| Condition absent for the clear count (default 2 runs) | Yes, event `recovered`, severity `info`; can be switched off | Once |

- "Worsens" is defined per check: any increase for defect and error counters, escalation only for gauges such as temperature and wear.
- Each notification states the previous value and the current value.
- Reasoning for the reminder defaults: a critical finding means "replace now", and a replacement usually takes a few days to arrange. A reminder twice a week keeps it visible without the daily repetition that makes smartd mail a nuisance. A warning means "plan a replacement"; once a week is enough. A notice needs no action, so it is not repeated.

### When an event is notified

- When the counter is above its baseline and the event cool-down for this drive and check has passed (default 24 hours). The message states the old and the new value. After successful delivery the baseline moves to the current value.
- If a counter is lower than its baseline (firmware reset), the baseline is lowered silently.

### Drives that disappear or stop answering

- A drive that was present and is absent for 2 consecutive runs produces one notification, event `missing`, severity warning. The record is kept for the retention period so that a returning drive is recognized.
- A drive that returns is not announced. Its conditions are evaluated as usual.
- Drives with a removable or USB transport and drives with an unstable identity are exempt.
- A drive that is listed but returns no usable SMART data for 2 consecutive runs gets the condition "unreadable", severity warning.
- While a drive is missing or unreadable, its other conditions are frozen: no reminders, no recovery.

### Grouping

- All notifications due for one drive in one run are combined into one message. Its severity is the highest among them.
- If more than `max_drive_notifications` drives (default 3) have a message due in one run, a single summary message is sent instead. It lists every affected drive with its findings and carries no per-drive metadata fields.

### First run

- When there is no state, the run records all baselines and all active conditions as already notified and sends exactly one summary: which drives are monitored, which were skipped, and which findings already exist. Its severity is that of the worst finding, or `info` if there is none.
- This message also proves that the notification route works. It can be switched off.
- A drive that appears later is not a first run. Its existing conditions are reported once in a normal per-drive message; its event counters start from their current values.

### Problems of the tool itself

- Conditions such as "smartctl not found", "configuration invalid", "state file was corrupt" or "controller cannot be queried" follow the same rules as drive conditions, on a pseudo-device named after the tool: reported once, reminded per severity, cleared with a recovery message.
- A run that ends with an unhandled error makes the service fail. `pve-smart-alert-failure.service` then sends a plain mail to `root` with a few lines of shell, without using the tool's own code. It is limited to one mail per day by a stamp file under `/run`.

### Delivery and state

- The state transition that belongs to a notification is committed only after the notification was handed over ([ADR 0007](0007-state-storage.md), [ADR 0008](0008-notification-integration.md)). A failed handover leads to a new attempt on the next run with current data.
- Notifications are never queued as rendered text. A message that is retried describes the situation at the time it is finally sent.

### Limits that follow from these rules

- At most `max_drive_notifications` notifications per run about drives, plus at most one about the tool itself.
- For an unchanged condition: one notification, then one per reminder interval.
- For a condition that worsens continuously at the same severity: at most one notification per cool-down period per drive.

### Defaults

| Setting | Default |
| --- | --- |
| Reminder interval | critical 3 d, warning 7 d, notice never |
| Worsening cool-down per drive | 6 h |
| Event cool-down per drive and check | 24 h |
| Confirmation count | 1 run; temperature 2 runs |
| Clear count | 2 runs |
| Missing and unreadable count | 2 runs |
| `max_drive_notifications` | 3 |
| Recovery notifications | on |
| First-run summary | on |

All of them are configuration keys ([ADR 0011](0011-configuration.md)).

## Consequences

- An unchanged problem costs one message and then follows a predictable reminder schedule.
- A failing fan in a 24-bay chassis produces one summary, not 24 messages.
- An old CRC error count never alerts. A rising one does.
- Replacing a disk produces one "missing" message for the old drive. Combined with the new drive's record, it documents the replacement.
- Recovery messages make it possible to close an incident. They add one message per incident.
- A notification can be delayed by confirmation and by the cool-down. An escalation to a higher severity is never delayed by the cool-down.
- There is no way yet to acknowledge a known condition other than a per-drive override in the configuration. An `ack` command is on the roadmap.

## Revisit when

- Real use shows that a default produces noise or hides something.
- Users with hosts that pass disks or controllers through to guests report false "missing" alerts.
