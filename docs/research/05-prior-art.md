# Research 05: Prior art

- Research date: 2026-10-03
- Used by: [PROJECT.md](../../PROJECT.md), [ADR 0010](../adr/0010-health-evaluation-and-default-thresholds.md), [ADR 0016](../adr/0016-test-strategy.md), [ADR 0017](../adr/0017-scope-of-version-1.md)

## Summary

Nothing was found that combines the three things PVE SMART Alert is about: evaluation with meaningful thresholds, repeat suppression, and delivery into the Proxmox VE notification system with a real severity.
The closest tools either alert through their own channels and need a monitoring stack, or they are small scripts that mail `root` without state.

| Project | Type | Evaluates | Suppresses repeats | Proxmox VE notifications | RAID pass-through | Footprint on the host |
| --- | --- | --- | --- | --- | --- | --- |
| smartd (built in) | Daemon | Fixed, small set | Daily repeat by default | As `system-mail`, severity `unknown` | MegaRAID by scan, others by hand | Already there |
| Scrutiny | Web application, collector, database | Yes, vendor thresholds plus observed failure rates | Not checked | No, own channels | Whatever smartctl supports, partly by hand | Containers, database |
| smartctl_exporter | Prometheus exporter | No, exports metrics | Alertmanager | No | Open request for `-d` types | Exporter plus Prometheus stack |
| check_smart | Monitoring plugin (Perl) | Yes | Done by the monitoring system | No | Yes, many types | Needs Nagios, Icinga or similar |
| Pulse | Monitoring application for Proxmox | Own alerting, details not checked | Not checked | No, own alerts | Through its agent | Separate application |
| PVE Disk Health Tool (community-scripts) | Interactive report | Shows values | – | – | Not stated | Script, on demand |
| proxmox-disk-health (jackedtea) | Bash script with systemd timers | Few fixed thresholds | Not found | As `system-mail` via mail to root | No | Script |
| Forum wrapper `pve-notify` | Bash and Perl snippet | – | – | Yes, through `PVE::Notify` | – | Templates in `/etc/pve` |

All rows are **Verified** against the projects' own descriptions unless noted. None of the tools was installed or run.

## smartd

See [Research 02](02-builtin-smart-handling.md). It is the baseline every Proxmox VE host already has.

Learned:

- Its scan is the same as `smartctl --scan`, so the device discovery is proven on a very large installed base.
- Its 30-minute interval is a long-standing default on a very large installed base.
- Its defaults are too coarse for prediction and too noisy in the wrong places, and tuning them means maintaining `smartd.conf` by hand per drive.

Done differently: thresholds on raw counters, per-drive overrides in one file, worsening detection, severity, and no daily repeat for an unchanged condition.

## Scrutiny

A dashboard that "merges manufacturer provided S.M.A.R.T metrics with real-world failure rates". Web interface, collector and InfluxDB, usually deployed with Docker. MIT license.

Its own motivation, quoted from the README:

- "smartd does not differentiate between critical and informational metrics"
- thresholds "are set by the manufacturer. In some cases these thresholds are unset, or are so high that they can only be used to confirm a failed drive, rather than detecting a drive about to fail"
- "smartd does not record S.M.A.R.T attribute history"

Learned:

- The collector is a thin wrapper around `smartctl --scan` and `smartctl --json`. This shows that the JSON output is a sufficient data source.
- The failure-rate table derived from Backblaze data ([Research 03](03-smart-indicators.md)) is the best public basis for default thresholds. It is MIT licensed and can be used with attribution.
- Its recorded smartctl outputs are a ready source of test fixtures.
- "All RAID controllers supported by smartctl are automatically supported", but the collector needs manual device type overrides when the scan is incomplete. The same limitation applies to PVE SMART Alert.

Done differently: no web interface, no database, no containers, nothing to operate. Scrutiny's default collection interval is once a day; PVE SMART Alert checks every 30 minutes because its purpose is alerting, not history. Alerts go into the Proxmox VE notification system instead of a separate set of channels.

## smartctl_exporter (Prometheus)

Exports smartctl data as metrics. Needs smartmontools 7.0 or later and root. Polls every 60 seconds by default and rescans devices every 10 minutes.

Learned:

- 7.0 is the minimum version for JSON.
- Its long-standing open request for `-d cciss,N` and `-d megaraid,N` shows how easily tools lose the device type when they treat the device name as sufficient.

Done differently: PVE SMART Alert is for hosts that have no metrics stack, or whose administrators want drive alerts next to their backup and replication alerts.

## check_smart

A monitoring plugin in Perl for Nagios-compatible systems. Supports ATA, SCSI, NVMe, MegaRAID, cciss and more, with device globs and options for bad-sector thresholds and attribute exclusions.

Learned: thresholds and exclusions per drive are a necessity in practice, not a luxury. State and repeat suppression live in the monitoring system, which is exactly the part a stand-alone host does not have.

## Pulse

A self-hosted monitoring application for Proxmox VE and other platforms with its own alerting. Reads most data through the Proxmox API; an optional agent collects SMART health and temperatures on hosts. MIT license.

Done differently: Pulse is a monitoring system to deploy and operate. PVE SMART Alert is a host-local tool with no interface of its own.

## Community scripts

- **PVE Disk Health Tool** (community-scripts, updated 2026-10-01): "A PVE host tool that reports drive health for all physical disks", interactive, can start a short self-test. It is a report, not a monitor.
- **proxmox-disk-health** (jackedtea): a Bash script with four systemd timers. Checks health, a few counters, temperature (55 °C / 65 °C) and NVMe used percentage (85 %). Sends mail to `root`, so the message enters the notification system as `system-mail`. Installation with `curl ... | bash`. No state handling or RAID support was found in its description.
- **Forum wrapper `pve-notify`** (2026-02): a few lines that call `PVE::Notify::notify` with a generic template placed in `/etc/pve/notification-templates/default/`. It shows that the Perl route works for third parties on current versions. See [Research 01](01-notification-integration.md).
- Several blog posts describe smartd with a custom mail address or with ntfy through the mail relay. They stay within smartd's fixed conditions.

Learned:

- People want this, and they solve it with small scripts. The scripts stop where the hard parts begin: state, repeat suppression, identity, RAID.
- The installation convention in this community is one command. PVE SMART Alert meets it with a Debian package instead of an unpacked script, so that upgrade and removal are clean.

## Commercial and general monitoring systems

Zabbix, Checkmk, Netdata and similar systems have SMART checks. They are the right answer for organizations that already run them. They are not an answer to "one command, then no further care" on a single host or a small cluster.

## What PVE SMART Alert takes over

1. smartctl JSON as the only data source (Scrutiny, smartctl_exporter).
2. Default thresholds founded on observed failure rates instead of vendor thresholds (Scrutiny, Backblaze).
3. Per-drive overrides and exclusions (check_smart, smartd).
4. Recorded outputs as test data (Scrutiny).
5. One-command installation (community scripts).

## What PVE SMART Alert does on purpose differently

1. No interface, no database, no container, no daemon.
2. Delivery through the Proxmox VE notification system with severity and metadata.
3. A problem is reported once, then only when it gets worse or when a reminder is due.
4. Drive identity by serial number, with the device node as an attribute.
5. Strictly read-only towards drives and host.

## Sources

- Scrutiny: <https://github.com/AnalogJ/scrutiny>
- smartctl_exporter: <https://github.com/prometheus-community/smartctl_exporter>
- check_smart: <https://github.com/Napsty/check_smart>
- Pulse: <https://github.com/rcourtman/Pulse>
- PVE Disk Health Tool: <https://community-scripts.org/scripts/disk-health>
- proxmox-disk-health: <https://github.com/jackedtea/proxmox-disk-health>
- Forum thread with the `pve-notify` wrapper: <https://forum.proxmox.com/threads/hook-custom-script-into-notifications-system.162766/>
- Blog "Set up scheduled SMART tests on Proxmox and send alerts via push notifications": <https://kovasky.me/blogs/proxmox_ntfy/>
