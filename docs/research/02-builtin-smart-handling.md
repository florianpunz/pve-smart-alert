# Research 02: What Proxmox VE already does about drive health

- Research date: 2026-10-03
- Applies to: Proxmox VE 9.2 (documentation 9.2.13, `pve-storage` `master`), smartmontools 7.4 as shipped with Proxmox VE 9 (`7.4-pve1` observed on 9.1).
- Used by: [ADR 0004](../adr/0004-smartctl-json-as-data-source.md), [ADR 0012](../adr/0012-read-only-and-coexistence-with-smartd.md), [ADR 0017](../adr/0017-scope-of-version-1.md)

## Summary

Proxmox VE has two independent mechanisms and neither is an alerting system with thresholds:

1. **smartd** runs with the stock Debian configuration and mails `root` for a small, fixed set of conditions. The mail enters the notification system as `system-mail` with severity `unknown`.
2. **The web interface** shows a health verdict and a wear-out value per disk on demand. It evaluates nothing, alerts on nothing, and cannot read drives behind RAID controllers.

The gap PVE SMART Alert closes: thresholds on the counters that actually predict failure, wear and spare monitoring, worsening detection, messages with full drive identity and a real severity, repeat suppression, and coverage of drives behind controllers that need a pass-through option.

## smartd on a Proxmox VE host

**Verified** in the administration guide:

> By default, the smartmontools daemon smartd is active and enabled, and scans any devices matching /dev/sd[a-z], /dev/sd[a-z][a-z], /dev/hd[a-t], or /dev/nvme[0-99] every 30 minutes for errors and warnings, and sends an e-mail to root if it detects a problem.

- `smartmontools` is a hard dependency of `libpve-storage-perl`. **Verified.**
- The Debian default configuration line is `DEVICESCAN -d removable -n standby -m root -M exec /usr/share/smartmontools/smartd-runner`. **Reported** (Proxmox wiki, Evolix wiki); not read from the package on a Proxmox VE 9 host.

What this configuration checks (**Verified** in `smartd.conf(5)`, smartmontools 7.4):

- Without explicit directives a device is monitored as with `-a`, which equals `-H -f -t -l error -l selftest -l selfteststs -C 197 -U 198`.
- A mail is sent for: failed health status (`-H`), failed usage attributes (`-f`), a growing ATA error log (`-l error`), a growing number of failed self-tests (`-l selftest`), a non-zero current pending sector count (`-C 197`), a non-zero offline uncorrectable count (`-U 198`), temperature limits if configured (`-W`, not configured by default), and failing SMART commands.
- Attribute changes tracked by `-t` are written to the system log only.
- Repetition: `-M once` sends one mail per type of problem and device and "is the default unless state persistence ('-s' option) is enabled". `-M daily` repeats the mail once per day and "is the default if state persistence ('-s' option) is enabled". The Debian build has state persistence enabled by default (state files under `/var/lib/smartmontools/`). On a Proxmox VE host smartd therefore **repeats its mail every day** for as long as a problem persists. This matches the forum reports of daily mails below.
- The check interval is 1800 seconds by default.
- For NVMe, `-H` checks the Critical Warning byte and `-l error` reports an increased number of error log entries.

What it does not do:

- No threshold on raw counters other than "non-zero" for 197 and 198. Reallocated sectors (5), reported uncorrectable errors (187), command timeouts (188) and CRC errors (199) never cause a mail.
- No wear or spare monitoring for SSDs beyond the NVMe Critical Warning byte.
- No notion of "worse than last time" apart from the error log and self-test counts.
- No severity. Every mail becomes a `system-mail` notification with severity `unknown` ([Research 01](01-notification-integration.md)).
- The mail contains the host name, the smartd message for the device node and smartd's device info line. It does not contain thresholds, previous values, the slot, or the pool or array the drive belongs to. **Assumed** from the smartd warning script; to be compared with a real mail.

Drives behind RAID controllers:

- `DEVICESCAN` uses the same device scan as `smartctl --scan`. On Linux this scan lists physical drives behind MegaRAID controllers as `/dev/bus/N -d megaraid,M`. smartd therefore does monitor MegaRAID drives. **Reported**: forum threads and a Red Hat knowledge base article show smartd messages such as `Device: /dev/bus/0 [megaraid_disk_11], Read SMART Self-Test Log Failed`.
- The same reports show the downside: smartd also picks up devices on the controller that are not disks or that do not answer SMART commands, and then mails daily about them.
- Controllers that need `-d cciss,N`, `-d areca,N`, `-d 3ware,N` or `-d aacraid,H,L,ID` are not found by the scan and need hand-written `smartd.conf` entries. **Verified** for the option syntax; the absence from the scan is **Assumed** from the lack of any report of such scan output.

Known user pain with smartd on Proxmox VE (**Reported**, Proxmox forum):

- Repeated mails for `Failed SMART usage Attribute: 190 Airflow_Temperature_Cel`, solved only by adding `-I 190` for the device in `smartd.conf`.
- Daily "disk failed" mails for an NVMe drive whose Percentage Used exceeded 100 and which therefore sets Critical Warning bit 2, although the drive still works and the available spare is above its threshold.
- Daily mails for a MegaRAID enclosure device that does not support SMART.

These are the cases the per-drive overrides and the wear policy of PVE SMART Alert are designed for.

## The web interface (Node → Disks)

**Verified** in `PVE::Diskmanage` (`pve-storage`):

- Device selection: block devices matching `sdX`, `hdX`, `vdX`, `xvdX`, `nvmeXnY` or `cciss!cXdY` under `/sys/block`.
- Commands: `smartctl -H <device>` for the health column of rotating disks, `smartctl -H -A -f brief <device>` for SSD-like devices and for the "Show S.M.A.R.T. values" dialog. Timeout 10 seconds. No `-d` option is ever passed.
- Exit status bits 0 and 1 are treated as errors; the other bits are ignored.
- Wear-out: for NVMe and SAS, parsed from the text line "Percentage Used" / "Percentage used endurance indicator" (`wearout = 100 - used`). For ATA, the normalized value of the first matching attribute from this list, which the web interface shows as `100 - value`. Checked again on 2026-10-07 in `get_wear_leveling_info` (**Verified**): the outer loop runs over the list and the inner loop over the attributes, so the order of the list decides; a name matches when it contains the name of the list (a regular expression without special characters); an attribute that matches without a value ends the search for that name. The list: `Media_Wearout_Indicator`, `SSD_Life_Left`, `Wear_Leveling_Count`, `Perc_Write/Erase_Ct_BC`, `Perc_Rated_Life_Remain`, `Remaining_Lifetime_Perc`, `Percent_Lifetime_Remain`, `Lifetime_Left`, `PCT_Life_Remaining`, `Lifetime_Remaining`, `Percent_Life_Remaining`, `Percent_Lifetime_Used`, `Perc_Rated_Life_Used`.
- The data is fetched when somebody opens the page or calls the API. Nothing is stored and nothing is compared.

Consequences:

- Drives behind MegaRAID or Smart Array controllers show `UNKNOWN` or an error in the web interface, because the logical volume does not answer SMART commands without `-d`. **Reported** in the forum thread "Disk smart status no longer working" for PERC H330/H730, HP P420i/H240 and MegaRAID 2108, with a reference to Proxmox bug 1127 and no fix announced. Users in that thread replaced `/usr/sbin/smartctl` with a wrapper script. PVE SMART Alert must never do anything like that.
- The NVMe namespace block device (`/dev/nvme0n1`) is queried, not the controller device. See [Research 03](03-smart-indicators.md) for why PVE SMART Alert uses the controller device.

## Other built-in alerting that touches drives

- **ZFS**: the ZFS event daemon (ZED) mails `root` on pool events such as errors. `ZED_EMAIL_ADDR` is `root` by default. **Verified** (Proxmox wiki "ZFS on Linux"). These mails are `system-mail` notifications as well.
- **mdraid**: not a supported technology in Proxmox VE. **Verified** (Proxmox wiki "Software RAID"). If `mdadm` is installed, its monitor mails `root` on array events. **Assumed.**
- **Hardware RAID**: array state is only visible through vendor tools. Nothing is installed or alerted by default. **Assumed.**
- **Ceph**: has its own device health tracking. Out of scope.

PVE SMART Alert looks at the drives, not at the arrays. Pool, array and volume state stay the business of ZED, mdadm and the vendor tools. PVE SMART Alert only names the pool or array a drive belongs to as context.

## Upstream plans

**Verified** on the Proxmox VE roadmap page: a planned "Health Checks" framework shall cover, among others, "RAID/disk state" on hosts and "integrate health-check results into the notification system". No design, patches or dates were found. If this lands, parts of PVE SMART Alert may become redundant or should integrate with it. Tracked in OPEN-QUESTIONS.

## How duplicate alerts are avoided

1. PVE SMART Alert does not use smartd, does not read its state and does not change its configuration. The two run side by side.
2. PVE SMART Alert notifications carry `type=pve-smart-alert` and a real severity; smartd mails carry `type=system-mail` and severity `unknown`. They can be routed to different targets.
3. A duplicate can only occur for the conditions smartd mails about (list above). For those conditions it does occur, and smartd repeats its mail daily by default. PVE SMART Alert cannot prevent this without editing `/etc/smartd.conf`, which belongs to another package.
4. Administrators who want no smartd mail can change that themselves. The documentation will describe the options: remove `-m root -M exec ...` from the `DEVICESCAN` line so that smartd only logs, switch it to `-M once`, or stop the service (the web interface does not depend on smartd). `pve-smart-alert doctor` will report whether smartd is active and configured to mail, so that the overlap is visible.
5. A matcher cannot filter smartd mails specifically, because all system mail shares the same metadata. This is a limitation of route A in [Research 01](01-notification-integration.md), not something PVE SMART Alert can change.

Whether the tool should offer an explicit, opt-in command that turns off smartd's mail was a question for the maintainer, because it would be an exception to the rule that the tool changes nothing but its own files. He decided on 2026-10-03 to keep version 1 as described above: documentation only ([ADR 0012](../adr/0012-read-only-and-coexistence-with-smartd.md)).

Background for a later revisit:

- A command that edits `/etc/smartd.conf` would have to be undone when the tool is removed. Otherwise the host is left without any SMART alert.
- A mechanism without that problem would be a systemd drop-in for the smartd service that starts smartd with an alternative configuration file without the mail directive. smartd accepts such a file with `-c FILE` (**Verified** in `smartd(8)`). The drop-in and the alternative file would be the tool's own files and would disappear with it. Whether this works cleanly with the service unit that Debian ships is **Assumed** and untested.

## Sources

- Proxmox VE Administration Guide, "Disk Health Monitoring" (9.2.13): <https://pve.proxmox.com/pve-docs/chapter-sysadmin.html>
- `PVE::Diskmanage`: <https://git.proxmox.com/?p=pve-storage.git;a=blob;f=src/PVE/Diskmanage.pm>
- `libpve-storage-perl` dependencies: <https://git.proxmox.com/?p=pve-storage.git;a=blob;f=debian/control>
- `smartd.conf(5)`, smartmontools 7.4: <https://manpages.debian.org/trixie/smartmontools/smartd.conf.5.en.html>
- `smartd(8)`, smartmontools 7.4: <https://manpages.debian.org/trixie/smartmontools/smartd.8.en.html>
- Proxmox wiki "Disk Health Email Alerts" (old, shows the Debian default line): <https://pve.proxmox.com/wiki/Disk_Health_Email_Alerts>
- Evolix wiki "Howto SMART": <https://wiki.evolix.org/HowtoSmart>
- Forum "Disk smart status no longer working": <https://forum.proxmox.com/threads/disk-smart-status-no-longer-working.82748/>
- Forum "SMART errors with Megaraid": <https://forum.proxmox.com/threads/smart-errors-with-megaraid.54722/>
- Forum "many emails from SMART Email Notifications": <https://forum.proxmox.com/threads/many-emails-from-smart-email-notifications.133932/>
- Forum "How to get rid of SMART Reliability notifications?": <https://forum.proxmox.com/threads/how-to-get-rid-of-smart-reliability-notifications.130103/>
- Forum "can not get disk smart information" (shows `smartmontools: 7.4-pve1` on Proxmox VE 9.1): <https://forum.proxmox.com/threads/can-not-get-disk-smart-information.181407/>
- Red Hat knowledge base, smartd message for a MegaRAID disk: <https://access.redhat.com/solutions/6566021>
- Proxmox wiki "ZFS on Linux": <https://pve.proxmox.com/wiki/ZFS_on_Linux>
- Proxmox wiki "Software RAID": <https://pve.proxmox.com/wiki/Software_RAID>
- Roadmap: <https://pve.proxmox.com/wiki/Roadmap>
