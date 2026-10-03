# ADR 0007: State in a node-local JSON file

- Status: Accepted
- Date: 2026-10-03

## Context

Without memory the tool would report every problem on every run.
To report a problem once, to notice that it got worse, to remind after an interval, to notice that a drive disappeared, and to tell a historic counter from a rising one, the tool must remember what it saw and what it already reported.

Requirements on the store:

- Survives reboots and package upgrades.
- Works when the cluster has no quorum, because a degraded cluster is exactly when drive alerts matter.
- Cannot be left half-written by a crash or a power loss.
- Can be read and repaired by an administrator with standard tools.
- Needs no additional package.

## Options considered

1. **A file on pmxcfs** (`/etc/pve/...`).
   Would make state visible cluster-wide. But drives belong to one node, pmxcfs is read-only without quorum, every write is replicated to all nodes, and it is Proxmox VE's configuration store. The tool must not write there ([ADR 0012](0012-read-only-and-coexistence-with-smartd.md)).
2. **SQLite** under `/var/lib` (module in the Python standard library).
   Transactions and history for free. But there is no query the tool needs that a dictionary lookup cannot answer, a binary file is harder to inspect and to put into a bug report, and schema migrations are heavier.
3. **One JSON file** under `/var/lib`, replaced atomically.
   Readable with `cat` and `jq`, trivial to back up, to anonymize and to use as a test fixture. Fine for the data volume: a few kilobytes per drive.
4. **One file per drive.**
   Avoids rewriting everything, but a run is no longer one atomic change and tool-wide state needs yet another file.
5. **Deriving state from the journal or from smartd's state files.**
   Not reliable and not owned by the tool.

## Decision

State is kept in **`/var/lib/pve-smart-alert/state.json`**, owned by root, mode 0600.

Content:

- A schema version.
- Per drive, keyed by identity ([ADR 0005](0005-drive-discovery-and-identity.md)): identity attributes, last known path and type, first and last time seen, a counter of consecutive runs in which the drive was missing or unreadable, the baselines of event counters, and the active conditions with severity, first detection, last notification and the value at the last notification.
- Tool-level conditions, such as "smartctl not found" or "configuration invalid".
- Information about the last run.

It does **not** contain a time series. Worsening is detected by comparing with the value at the last notification, which needs one stored value per condition.

Rules:

- **Atomic replacement.** The new state is written to a temporary file in the same directory, flushed to disk, and renamed over the old file. A crash leaves either the old or the new state.
- **Commit after delivery.** A state change that goes with a notification is written only if the notification was handed over successfully ([ADR 0009](0009-notification-policy.md)). If delivery fails, the state stays as it was and the next run plans the same notification again from fresh data. No separate outbox is needed.
- **One writer.** A lock file under `/run` is held for the whole run.
- **Corruption.** If the file cannot be parsed or fails validation, it is renamed to `state.json.corrupt-<timestamp>`, the run continues with empty state, and a tool-level condition is raised. The next notification is then the first-run summary, not a flood of individual alerts.
- **Migration.** Each schema version has a migration function to the next one. An unknown newer version is treated like corruption, which protects against a downgrade silently misreading the file.
- **Retention.** Records of drives that have not been seen for 90 days are removed.
- **Timestamps** are UTC in ISO 8601. If a stored timestamp lies in the future, it is treated as "now", so that a clock jump cannot suppress reminders forever.
- **No personal data** beyond drive model, serial number and WWN.

A second file, `/var/lib/pve-smart-alert/last-good-config.json`, holds the last configuration that passed validation ([ADR 0011](0011-configuration.md)).

## Consequences

- State is per node. Each cluster node knows only its own drives. This matches where the drives are and keeps alerting independent of quorum.
- An administrator can reset the tool by deleting one file. The next run then behaves like a first run.
- There is no history for trend graphs or rate-based rules such as "more than ten new bad sectors per day". If such rules are wanted later, a history store is added next to the state file with its own decision record.
- At-least-once delivery: if the process dies after handing over a notification and before writing the state, the notification is sent again on the next run. This is rare and preferable to losing an alert.
- The file contains serial numbers. It is readable by root only, and the fixture tool anonymizes them ([ADR 0016](0016-test-strategy.md)).

## Revisit when

- Rate-based or trend-based checks are added.
- A cluster-wide view is wanted. That would be a reporting feature on top of per-node state, not a change of where state lives.
