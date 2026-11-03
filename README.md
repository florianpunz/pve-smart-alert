<img alt="pve-smart-alert" src="docs/img/banner.png" />

<h1 align="center">PVE SMART Alert</h1>

<p align="center">
  <a href="#installation"><b>Install</b></a> ·
  <a href="docs/check-catalog.md"><b>Checks</b></a> ·
  <a href="docs/hardware-support.md"><b>Hardware</b></a> ·
  <a href="docs/troubleshooting.md"><b>Troubleshooting</b></a> ·
  <a href="ROADMAP.md"><b>Roadmap</b></a>
</p>

SMART drive alerts for Proxmox VE. `pve-smart-alert` checks every drive of a host
every 30 minutes and reports problems through the Proxmox VE notification system,
with real severities and without repeating itself.

> **Status: pre-1.0.** Release `0.5.1` is tested on a standalone host and a
> three-node cluster; SAS and hardware RAID are tested on recorded data.
> Version 1.0, the release meant for regular use, is in progress: [ROADMAP.md](ROADMAP.md).

## Why

Proxmox VE already has smartd and a SMART view in the web interface. Both leave gaps:

- **smartd mails, but does not judge.** No thresholds on the counters that predict
  failure, no wear or spare, every mail has severity `unknown`, and it repeats daily.
- **The web interface shows, but never alerts.** And it shows nothing for drives
  behind a RAID controller.
- **Scrutiny, Zabbix, Checkmk & co. work,** but they are a system to operate.

PVE SMART Alert sits in between: nothing to operate, thresholds that mean something,
memory between runs, and delivery to the targets you already configured.

## What it does

| | |
|---|---|
| Drives | SATA, SAS and NVMe, found automatically, including ZFS, md and LVM members |
| RAID controllers | MegaRAID / PERC automatically, HPE Smart Array experimentally, others by a manual entry ([hardware support](docs/hardware-support.md)) |
| Checks | Health verdict, defect and error counters, wear, spare, temperature, self-tests, missing and unreadable drives ([check catalog](docs/check-catalog.md)) |
| Alerts | Once per problem; again on escalation, worsening, reminder and recovery |
| Delivery | Proxmox VE notification system with severity, mail to root as fallback |
| Configuration | One TOML file, global and per-drive overrides; defaults need none |
| Footprint | Python, Perl and smartmontools, all already on the host |

## What it is not

- **Not a pool monitor.** ZFS, mdadm and RAID volume state belong to ZED, mdadm and vendor tools.
- **Not a test scheduler.** It reads self-test results, it never starts a test.
- **Not a dashboard.** No web interface, no metrics export, no history.
- **Not invasive.** It only reads drives and changes nothing on the host except its own
  files; smartctl may create device nodes for some RAID controllers. It leaves smartd alone.

## Installation

As root, on every node:

```sh
wget -qO- https://github.com/florianpunz/pve-smart-alert/releases/latest/download/install.sh | sh
```

The script verifies the checksum and installs the package with apt;
`PVE_SMART_ALERT_VERSION=0.5.1` pins a version. Without the script:

```sh
wget -qO /tmp/pve-smart-alert.deb https://github.com/florianpunz/pve-smart-alert/releases/latest/download/pve-smart-alert.deb \
  && apt install -y /tmp/pve-smart-alert.deb
```

After the installation:

- The first check runs at once and sends one summary; then a timer runs it every 30 minutes.
- On Proxmox VE 9 no other package is pulled in. `apt purge pve-smart-alert` removes
  everything, configuration and state included.
- If a run fails, root gets a short mail, at most once a day and once more after a reboot.
- To build the package yourself: `make deb` (needs build-essential, dpkg-dev, debhelper).

**Change the interval** with a drop-in, which survives upgrades:
`systemctl edit pve-smart-alert.timer`. Empty `OnUnitActiveSec=` first, then set both
timers again ([systemd.timer(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)):

```ini
[Timer]
OnUnitActiveSec=
OnBootSec=3min
OnUnitActiveSec=1h
```

## Configuration

`/etc/pve-smart-alert/config.toml` holds only what differs from the defaults.
Every key with its default is in `/usr/share/doc/pve-smart-alert/config.reference.toml`.

```toml
[checks."wear"]
warning = 90            # warn at 90 % instead of 95 %

[[drive]]
serial = "S4EWNX0M000000A"
comment = "Worn, replacement ordered"

[drive.checks."wear"]
enabled = false
```

A file that does not validate never stops a run: the last good configuration is used
and the error is reported. `pve-smart-alert config check` names the line.

## Commands

| Command | Does |
| --- | --- |
| `doctor` | Checks everything the tool depends on, one line each |
| `scan` | Lists every drive found, and what became of it |
| `check` | Runs one check and sends what is due; the timer calls it |
| `check --dry-run` | Shows findings and due notifications, sends nothing |
| `status` | Last run and active problems per drive; `--json` for the raw state |
| `config check` / `config show` | Validates the configuration / shows every effective value and its origin |
| `test-notification` | Sends a test and names the matchers that route it; `--severity`, `--transport` |
| `dump-fixture --all` | Writes an anonymized recording of your drives, to attach to an issue |

Details: `man pve-smart-alert`.

## What is notified

| Event | Rule |
| --- | --- |
| New problem | Once; a temperature first has to show in 2 runs in a row |
| Severity rises | At once |
| Value worsens at the same severity | At most every 6 hours per drive |
| Reminder | Critical after 3 days, warning after 7 days, notice never |
| Problem gone for 2 runs | Once, as recovered (`info`) |
| Counter rises (e.g. CRC errors) | When it rises; an old value never alerts |
| Drive missing or unreadable for 2 runs | Once; removable and USB drives are never "missing" |

All findings of one drive in one run are one message; more than 3 drives at once become
one summary. Problems of the tool itself follow the same rules. Every number is a key
of `[notify]` ([ADR 0009](docs/adr/0009-notification-policy.md)).

Exit status of a run:

| Status | Meaning | Failure mail |
| --- | --- | --- |
| 0 | Run completed, whatever the drives' health | no |
| 1 | A notification could not be handed over; retried next run | yes |
| 3 | Another run holds the lock | no |
| 130 | Interrupted with Ctrl+C | no (terminal only) |

## Notification routing

Notifications have the type `pve-smart-alert`. The unchanged default matcher routes
them, so nothing needs to be set up.

If you restricted the default matcher, they are **dropped without an error**. Add a
matcher for them, as root on one node, and route all four severities:

```sh
pvesh create /cluster/notifications/matchers \
  --name pve-smart-alert \
  --target <TARGET> \
  --match-field 'regex:type=^pve-smart-alert$' \
  --match-severity info,notice,warning,error
```

`<TARGET>` comes from `pvesh get /cluster/notifications/targets`. To check the routing:

- `pve-smart-alert doctor`: the lines `routing` and `fallback` warn when a severity, or
  the fallback mail to root, reaches no enabled target.
- `pve-smart-alert test-notification --severity warning`: names the matchers that route it.

Both are hints, not delivery receipts. Run `doctor` again after changing matchers or
upgrading Proxmox VE.

## Coexistence with smartd

smartd mails root about some of the same problems, daily, so some arrive twice.
`doctor` shows in the line `smartd` whether it does. To quiet it, edit the `DEVICESCAN`
line in `/etc/smartd.conf`, then `systemctl restart smartmontools`:

- remove `-m root -M exec /usr/share/smartmontools/smartd-runner`: log to the journal only, or
- add `-M once` after `-m root`: mail each problem only once.

The web interface does not depend on smartd. The tool never changes it
([ADR 0012](docs/adr/0012-read-only-and-coexistence-with-smartd.md)).

## Documentation

- [Check catalog](docs/check-catalog.md): every check and its default thresholds
- [Hardware support](docs/hardware-support.md): controllers, how each was verified, recordings wanted
- [Troubleshooting](docs/troubleshooting.md): no notification, missing drive, failed run
- [Project](PROJECT.md) · [Requirements](REQUIREMENTS.md) · [Architecture](ARCHITECTURE.md) ·
  [Decisions](docs/adr/README.md) · [Research](docs/research/README.md)
- [Roadmap](ROADMAP.md) · [Open questions](OPEN-QUESTIONS.md) · [Traceability](docs/traceability.md)

## Development

Python 3.11+, GNU Make and git. A fresh clone needs only:

```sh
make check    # lint, format, types, repository rules and tests
```

`make test`, `make deb` and `make build` do what they say. Rules for contributions,
human or AI: [CONTRIBUTING.md](CONTRIBUTING.md) and [CLAUDE.md](CLAUDE.md).

## License

[AGPL-3.0-or-later](LICENSE), © 2026 Florian Punz ([ADR 0015](docs/adr/0015-license.md)).
Some test fixtures come from other projects and keep their licenses:
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Affiliation

An independent project, not affiliated with or endorsed by Proxmox Server Solutions GmbH.
Proxmox is a registered trademark of Proxmox Server Solutions GmbH; the name is used only
to say what the tool is for.
