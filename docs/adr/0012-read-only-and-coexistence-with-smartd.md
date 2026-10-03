# ADR 0012: Read-only operation and coexistence with smartd

- Status: Accepted
- Date: 2026-10-03

## Context

The maintainer's constraint: the tool must change nothing on the host except its own files, and it must survive a Proxmox VE upgrade.

A Proxmox VE host already runs smartd with the Debian default configuration ([Research 02](../research/02-builtin-smart-handling.md)).
smartd mails `root` for a subset of the conditions PVE SMART Alert reports, and on Debian it repeats that mail every day while the condition lasts.
Both tools will therefore report some problems. The question is what PVE SMART Alert does about that, and how far "its own files" reaches.

## Options considered

1. **Replace smartd**: stop and disable the service on installation.
   No duplicates. But it changes a service of another package, removes a safety net the administrator may rely on, and has to be undone on removal.
2. **Reconfigure smartd**: rewrite the `DEVICESCAN` line so that smartd logs but does not mail, or so that it calls a PVE SMART Alert script instead.
   Edits a configuration file owned by `smartmontools`. A later package upgrade then asks the administrator which version to keep. This is exactly the kind of host change the constraint forbids.
3. **Use smartd as the collector** and only replace its mailer.
   Covers only smartd's fixed conditions ([ADR 0004](0004-smartctl-json-as-data-source.md)).
4. **Coexist**: leave smartd alone, make the overlap visible, and document how an administrator can quiet smartd.
5. **Coexist, plus an explicit opt-in command** that quiets smartd on request.
   Convenient, but still an edit to another package's file, performed by the tool.

## Decision

### The host footprint rule

PVE SMART Alert creates, changes and removes only these things:

| Path | Purpose |
| --- | --- |
| Files installed by the `pve-smart-alert` package | Program, bridge, templates, units, documentation |
| `/etc/pve-smart-alert/` | Configuration |
| `/var/lib/pve-smart-alert/` | State |
| `/run/pve-smart-alert/` | Lock and stamp files |

It does not:

- edit, divert or replace a file that belongs to another package,
- write anywhere on pmxcfs (`/etc/pve`),
- change the configuration of smartd, ZED, mdadm, Postfix or the Proxmox VE notification system,
- enable, disable, start or stop a unit other than its own.

The two notification template files are installed below `/usr/share/pve-manager/templates/default/`. They are new files with the prefix `pve-smart-alert-`, owned by the `pve-smart-alert` package and removed with it. They are within the rule as it is written here. The reason they have to be in this directory is in [ADR 0008](0008-notification-integration.md).

### The drive footprint rule

PVE SMART Alert only reads from drives. It does not:

- enable SMART on a drive where it is disabled,
- start a self-test, an offline data collection or a firmware function,
- change a drive setting such as power management, error recovery control or automatic offline testing,
- wake a drive that is in standby.

If SMART is disabled on a drive, that is reported as a notice with the command the administrator can run.
Self-test results are evaluated if someone else runs self-tests. PVE SMART Alert does not schedule them.

### smartd

Option 4: **coexist**.

- smartd is not touched and not required. PVE SMART Alert works the same whether smartd is running or not.
- PVE SMART Alert notifications carry `type=pve-smart-alert` and a severity. smartd mail arrives as `type=system-mail` with severity `unknown`. The two can be routed differently, but smartd mail cannot be told apart from other system mail by a matcher.
- For the conditions smartd also detects, the administrator receives both, and smartd's daily repetition continues. This is accepted as the default.
- The documentation describes how to quiet smartd by hand: remove `-m root -M exec ...` from the `DEVICESCAN` line so that it only logs, or switch it to `-M once`, or stop the service. The web interface does not depend on smartd.
- `pve-smart-alert doctor` reports whether smartd is active and configured to mail.

Option 5 is not part of version 1. Whether it is wanted at all is a question for the maintainer. His answer is recorded in the [index of decision records](README.md).

## Consequences

- Installing and removing the tool leaves the rest of the host exactly as it was. Purging the package removes configuration and state as well.
- Nothing the tool does can conflict with a Proxmox VE upgrade through a modified foreign file. The remaining upgrade risk is the notification interface ([ADR 0008](0008-notification-integration.md)).
- Duplicate alerts for some conditions are the price of the footprint rule. The overlap is limited to smartd's conditions and is visible in `doctor`.
- smartd remains as an independent second line. If PVE SMART Alert stops working for any reason, the host is no worse off than before it was installed.
- No scheduled self-tests means that latent sector errors on rarely read areas are found later than they could be. Administrators who want self-tests configure them in smartd; PVE SMART Alert then reports their results.
- A drive with SMART disabled stays unmonitored until the administrator enables it. The notice makes that visible.

## Revisit when

- The maintainer decides that an opt-in command for quieting smartd is worth the exception.
- Users ask for self-test scheduling. It would need its own decision record, because it ends the read-only rule for drives.
