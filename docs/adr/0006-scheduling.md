# ADR 0006: Scheduling with a systemd timer, every 30 minutes

- Status: Accepted
- Date: 2026-10-03

## Context

Checks must run regularly without the administrator setting anything up, and the tool must not need care after installation.
A run consists of a device scan and one smartctl call per drive. On a host with a few dozen healthy drives this takes seconds.

## Options considered for the mechanism

1. **A daemon** with an internal loop, like smartd.
   Keeps state in memory, but needs supervision, signal handling and memory hygiene for a job that is idle more than 99 % of the time.
2. **cron** (`/etc/cron.d`).
   Simple and present. No overlap protection, no catch-up after downtime, no dependency ordering at boot, output goes to mail by default, which would itself enter the notification system as `system-mail`.
3. **A systemd timer with a oneshot service.**
   No resident process. Overlap is impossible because a oneshot service is not started while it is active. Output goes to the journal. Ordering after other units, resource limits, a run-time limit and a failure hook are declarative. The run can be started by hand with `systemctl start`.
4. **Proxmox VE's own job scheduler.**
   Internal to Proxmox VE and not meant for third-party jobs.

## Options considered for the interval

| Interval | Argument for | Argument against |
| --- | --- | --- |
| 5 minutes or less | Fast reaction to temperature | SMART counters do not change that fast; more load on drives; more exposure to drives that react badly to frequent queries |
| **30 minutes** | Default of smartd for decades on a huge installed base; worst-case detection delay of half an hour is short compared with how drive failures develop | None found |
| 60 minutes | Half the calls | Doubles the delay for sudden events such as overheating or a burst of pending sectors, for no measurable saving |
| Daily (Scrutiny's default) | Enough for trend dashboards | Too slow for alerting |

Accumulating counters reduce the importance of the interval further: reallocations, media errors and the NVMe over-temperature timers keep their history, so an event between two runs is still seen at the next run.

## Decision

- A **systemd timer** `pve-smart-alert.timer` starts a **oneshot service** `pve-smart-alert.service` that runs `pve-smart-alert check`.
- The timer is monotonic: first run 3 minutes after boot (`OnBootSec`), then every **30 minutes** after the previous start (`OnUnitActiveSec`).
  - If the timer is started when the system has been up for longer, the first run starts immediately. Installing the package therefore triggers the first check right away.
  - Cluster nodes run at different moments without extra configuration, because their boot and installation times differ.
  - Clock changes do not affect the schedule.
- The service is ordered after `pve-cluster.service`, because the notification configuration lives on pmxcfs. It does not require that service: if pmxcfs is unavailable, the check still runs and the fallback transport is used ([ADR 0008](0008-notification-integration.md)).
- The service runs with reduced CPU and I/O priority and has an upper run-time limit, so that a host with many unresponsive drives cannot pile up runs.
- A failed run triggers `pve-smart-alert-failure.service` through `OnFailure=`. That unit reports the failure through a path that does not depend on the tool's own code ([ADR 0009](0009-notification-policy.md)).
- Manual invocations of `pve-smart-alert check` take the same lock as the service, so a manual run and a timer run cannot overlap.
- The interval is changed with a systemd drop-in (`systemctl edit pve-smart-alert.timer`). It is deliberately not a key in the tool's configuration file: the timer belongs to systemd, and a drop-in survives package upgrades.
- All time-based policies of the tool (reminders, cool-downs, confirmation) are expressed as durations or as numbers of runs in the configuration and are independent of the timer interval, except where a number of consecutive runs is counted.

## Consequences

- No process is resident between runs.
- The worst-case delay between an event and its notification is about 30 minutes, or two runs for checks that need confirmation ([ADR 0010](0010-health-evaluation-and-default-thresholds.md)).
- Together with smartd, drives are queried by two tools at the same interval. This doubles a very small load.
- A run right after boot may happen before pmxcfs is ready. Ordering covers the normal case and the fallback transport covers the rest.
- Administrators who expect a configuration key for the interval need to be pointed to the drop-in. The documentation and `pve-smart-alert doctor` show the active schedule.

## Revisit when

- Drives or controllers are reported to misbehave when queried every 30 minutes.
- A use case needs reactions faster than the interval, which would call for a different design rather than a shorter timer.
