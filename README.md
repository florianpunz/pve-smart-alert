<img alt="pve-smart-alert" src="docs/img/banner.png" />

<h1 align="center">PVE SMART Alert</h1>

`pve-smart-alert` checks the SMART data of every drive in a Proxmox VE host at regular intervals and reports problems through the Proxmox VE notification system.

> **Status: early development.** The tool finds, reads and evaluates the drives of a host, remembers what it reported, and sends a notification when a problem appears, gets worse, needs a reminder or clears. The package brings a systemd timer that runs the check every 30 minutes. M5 is accepted on the standalone host `pve1` and on the cluster node `pve5`; there is no public release yet, because the repository is still private.
>
> <details>
> <summary>Next: M6 and M7</summary>
>
> - **M0 (done):** development tooling
> - **M1 (done):** the notification route (two transports and the Perl bridge), the two commands below and the Debian package that ships them
> - **M2 (done):** discovery and collection for SATA and NVMe drives
> - **M3 (done):** evaluation and configuration
> - **M4 (done):** state and notification policy
> - **M5 (accepted on pve1 and pve5):** packaging, timer and installation
> - **M6 (built, waits for its runs on a cluster node):** SAS and hardware RAID on recorded data; [docs/hardware-support.md](docs/hardware-support.md) says how each controller was verified
> - **M7 (started):** hardening, documentation and version 1.0, the version meant for regular use
>
> </details>

## Planned features

- **Automatic discovery:** finds all SATA, SAS and NVMe drives, including drives behind MegaRAID controllers and, experimentally, SSSRAID and HPE Smart Array; the drives behind other RAID controllers that smartctl can reach are added by hand ([docs/hardware-support.md](docs/hardware-support.md))
- **Predictive thresholds:** judges drives by thresholds that predict failure instead of merely confirming it
- **No repeat alerts:** reports a problem once, and again only when it gets worse or a reminder is due
- **Real severities:** sends messages through the targets and matchers configured under Datacenter → Notifications
- **Simple operation:** installs with one command and runs without care afterwards
- **Read-only:** only reads from drives and changes nothing on the host except its own files; smartctl itself may create the device nodes of some RAID controllers

## Installation

There is no public release yet: the repository is still private, and the download URLs below work once it is public. Until then, `make deb` builds the package into `dist/` on a Debian or Proxmox VE host with build-essential, dpkg-dev and debhelper; copy it to each node and install it there as root with `apt install ./pve-smart-alert_*_all.deb`.

Once a release is published, either command installs the newest one on a node, as root ([ADR 0013](docs/adr/0013-packaging-and-installation.md)); on a cluster, run it on each node:

```sh
# Download the package and install it with apt
wget -qO /tmp/pve-smart-alert.deb https://github.com/florianpunz/pve-smart-alert/releases/latest/download/pve-smart-alert.deb \
  && apt install -y /tmp/pve-smart-alert.deb

# The same, with the checksum verified; PVE_SMART_ALERT_VERSION=0.5.0 pins a version
wget -qO- https://github.com/florianpunz/pve-smart-alert/releases/latest/download/install.sh | sh
```

The package enables a systemd timer that runs the first check right away and then one every 30 minutes; the first check sends one summary.

- On a Proxmox VE 9 host it pulls in no other package. `apt purge pve-smart-alert` removes it together with its configuration and state, and with everything below `/usr/share/pve-smart-alert` ([ADR 0035](docs/adr/0035-purge-removes-the-package-directory.md)).
- The installation enables and starts `pve-smart-alert.timer`. It starts `pve-smart-alert check` 3 minutes after boot and then 30 minutes after the start of the previous run; on a host that is already up, the first run is expected right after the installation, which sends the first-run summary. `systemctl list-timers pve-smart-alert.timer` shows the next run, `journalctl -u pve-smart-alert.service` the runs.
- The interval is changed with a drop-in, not in the configuration file of the tool; a drop-in survives upgrades of the package. The timers that a drop-in sets are added to those of the package, and an empty `OnUnitActiveSec=` removes all of them, `OnBootSec=` included ([systemd.timer(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)). So the drop-in, which `systemctl edit pve-smart-alert.timer` opens, first empties `OnUnitActiveSec=` and then sets both. For a run every hour:

  ```ini
  [Timer]
  OnUnitActiveSec=
  OnBootSec=3min
  OnUnitActiveSec=1h
  ```

- When a run fails, a short mail to root says so, at most once a day and once more after a reboot. It is sent without the code of the tool, so it also arrives when that code is broken.
- The configuration is `/etc/pve-smart-alert/config.toml`. `/usr/share/doc/pve-smart-alert/config.reference.toml` lists every key with its default.
- These keys have an effect so far: `transport` in `[notify]` (`auto`, the default, sends through the notify bridge with mail to root as the fallback, `pve-notify` through the bridge only, `mail` as mail to root only), the settings of the notification policy in `[notify]` and `[notify.reminder]` (grouping limit, recovery and first-run messages, cool-downs, counts of runs, reminder intervals), `[smartctl]` and the manual devices in `[[discovery.device]]`, which `scan` and `dump-fixture` use, the exclude rules of `[discovery]`, `probe_cciss` in `[discovery]`, which switches the experimental probe for the drives behind an HPE Smart Array controller off (it is on by default and runs on hosts with the driver `hpsa`), the thresholds, the enabled state and the confirmation count of every check in `[checks."<check-id>"]`, the enabled state of every condition of the tool itself in the same table, such as `enabled = false` in the table `[checks."tool.unsupported_controller"]` for a controller in HBA mode whose drives all appear in `scan`, and the per-drive overrides in `[[drive]]`, which can exclude a drive, set its smartctl detail level and override any check for it. A file that does not validate never stops a run: the last configuration that passed is used and the problem is reported.

## Commands

The installed tool has these commands:

| Command | Does |
| --- | --- |
| `pve-smart-alert doctor` | Reports one line per part of the host the tool works with: configuration, smartctl, notify bridge, templates, mail command, the routing of notifications and of the fallback mail to root, the state file with the last run, the timer with its schedule and next run, the Proxmox VE version, whether smartd mails root, in the line `controllers` a controller whose drives smartctl cannot read, such as one with the driver `mpi3mr`, and in the line `probe` the HPE Smart Array controllers of the host and whether their drives are probed (FR-603, FR-109, FR-103) |
| `pve-smart-alert scan` | Finds the drives of the host and reads them in the order scan, probe, manual entries; a drive that two sources find is read twice and kept once. It shows every device with its source and what became of it; for a drive its model, serial number, class, what uses it, its wear value with the source and, behind a MegaRAID or HPE Smart Array controller, the controller and the device ID; a drive behind another controller shows the node and type instead (FR-108, [ADR 0034](docs/adr/0034-manual-entries-of-other-pass-through-types.md)). Above the devices it names a controller whose drives smartctl cannot read, so that they are not monitored (FR-109), and every HPE Smart Array controller with the drives the probe found behind it, or why it was not probed (FR-103) |
| `pve-smart-alert check` | Runs one check: evaluates every drive against the checks of the [check catalog](docs/check-catalog.md), compares the result with the state of earlier runs and sends the notifications that are due (FR-601). The first run sends one summary. The state is `/var/lib/pve-smart-alert/state.json`; deleting it makes the next run a first run |
| `pve-smart-alert check --dry-run` | Prints the findings and the notifications a run would send now, without sending anything or changing the state |
| `pve-smart-alert status` | Shows from the state the last run and every drive with its active conditions (FR-602); `--json` prints the state as JSON |
| `pve-smart-alert config check` | Validates the whole configuration file and names the first error, with its key where it has one and its line where it can be found; the exit status is then non-zero (FR-405) |
| `pve-smart-alert config show` | Prints every key with its effective value and where the value comes from, the file or the built-in default (FR-407); `--defaults` prints the built-in ones |
| `pve-smart-alert dump-fixture --all` or `pve-smart-alert dump-fixture DEVICE...` | Writes the drive data of the host as an archive in which serial numbers, WWNs and UUIDs are replaced by placeholders, to attach to an issue (FR-604) |
| `pve-smart-alert test-notification` | Sends one test notification, prints what the notification system did with it and names the matchers that route it (FR-520) |

Options of `test-notification`:

- `--severity SEVERITY`: `info` (default), `notice`, `warning` or `error`
- `--transport TRANSPORT`: `auto`, `pve-notify` or `mail`, as for `transport` in the configuration; without the option the configuration decides.

## What is notified

The policy is that of [ADR 0009](docs/adr/0009-notification-policy.md); every value below is a key of `[notify]`.

- A problem is notified once. It is notified again at once when its severity rises, when its value worsens at the same severity (at most every 6 hours per drive), and as a reminder: after 3 days for a critical finding, after 7 days for a warning, never for a notice. A temperature has to be seen in 2 runs in a row first.
- A problem that is absent for 2 runs is notified as recovered, with severity `info`.
- A rising error counter, such as the CRC errors of a cable, is notified when it rises; an old value never is.
- A drive that is absent for 2 runs is notified once as missing; one that answers without usable data for 2 runs as unreadable. Removable and USB drives are never reported as missing.
- All findings of one drive in one run are one message. When more than 3 drives have a message due in the same run, one summary replaces them.
- Problems of the tool itself, such as a missing smartctl or an invalid configuration, follow the same rules.

A run exits with status 0 when it completed, whatever the health of the drives; 1 when a notification could not be handed over, which is then planned again on the next run; 3 when another run holds the lock; and 130 when the command was interrupted with Ctrl+C, which says so instead of ending in a traceback. The service treats 3 as a success; every other status but 0 counts as a failed run and sends the failure mail. A command typed in a terminal sends no failure mail; the service is stopped with SIGTERM rather than interrupted with Ctrl+C.

## Coexistence with smartd

Proxmox VE runs smartd, and its default configuration mails root about some of the problems this tool reports, every day while they last. PVE SMART Alert leaves smartd alone ([ADR 0012](docs/adr/0012-read-only-and-coexistence-with-smartd.md)), so some problems arrive twice; `pve-smart-alert doctor` says in the line `smartd` whether smartd mails. To quiet smartd by hand, edit the `DEVICESCAN` line in `/etc/smartd.conf` and restart it with `systemctl restart smartmontools`:

- remove `-m root -M exec /usr/share/smartmontools/smartd-runner`, so that smartd only logs to the journal, or
- add `-M once` after `-m root`, so that it mails each problem only once.

The Proxmox VE web interface does not depend on smartd.

## Notification routing

Notifications have the type `pve-smart-alert` and reach a target only through a matcher under Datacenter → Notifications. The unchanged default matcher matches them, so no setup is needed. If the default matcher has been restricted, for example to the types `vzdump` and `system-mail`, the notifications are accepted and then dropped without an error.

In that case, add a matcher with the rule `type` as regex `^pve-smart-alert$` and the target you want, in the web interface (Datacenter → Notifications → Notification Matchers → Add) or on the command line, as root on one node:

```sh
pvesh create /cluster/notifications/matchers \
  --name pve-smart-alert \
  --target <TARGET> \
  --match-field 'regex:type=^pve-smart-alert$' \
  --match-severity info,notice,warning,error
```

Replace `<TARGET>` with a target name from `pvesh get /cluster/notifications/targets`. Route all four severities: the tool also sends `info` messages, for recoveries and for the first summary, and `notice` findings. A matcher that leaves out a severity drops those messages.

### Check the routing

Two commands evaluate the matchers the way the notification system does:

- `pve-smart-alert doctor` reads the matchers and targets with `pvesh`:
  - `routing` is `warn` when a severity of the tool reaches no enabled target. The line names that severity, and a matcher that would route it if it or its target were enabled.
  - `fallback` does the same for the mail to root that replaces a notification when the notify bridge fails. Proxmox VE routes it as the type `system-mail` with the severity `unknown`, so a default matcher limited to other types drops it too.
- `pve-smart-alert test-notification --severity warning` names the matchers that route the test, or says that none does.

Both give a hint, not a delivery receipt: a rule they cannot decide, such as a time rule, is reported as such, and only the target shows that a message arrived. Run `doctor` again after you change the matchers or upgrade Proxmox VE.

## Documentation

- [PROJECT.md](PROJECT.md): purpose, audience, comparison with existing solutions, scope of version 1
- [REQUIREMENTS.md](REQUIREMENTS.md): numbered, verifiable requirements
- [ARCHITECTURE.md](ARCHITECTURE.md): components, run sequence, configuration, state, notification, error handling
- [docs/check-catalog.md](docs/check-catalog.md): the checks and their default thresholds
- [docs/troubleshooting.md](docs/troubleshooting.md): what to do when no notification arrives, a drive is missing or was replaced, a run fails, or the configuration does not apply
- [docs/hardware-support.md](docs/hardware-support.md): which drives and controllers are supported, how each was verified, and how to contribute a recording of your hardware
- [docs/adr/](docs/adr/README.md): one record per architecture decision
- [docs/research/](docs/research/README.md): evidence behind the decisions, with sources
- [ROADMAP.md](ROADMAP.md): milestones, each with a testable result, and the state of each
- [docs/traceability.md](docs/traceability.md): the tests and acceptance steps of every requirement, a dated snapshot
- [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md): what is not settled yet
- [CLAUDE.md](CLAUDE.md): binding rules for contributors and AI agents

## Development

Requires Python 3.11 or later, GNU Make and git.

```sh
make check         # lint, format check, type check, repository rules and tests
make dev-install   # create the virtual environment and install the development tools
make test          # the test suite
make build         # the Debian package and the Python distribution
make deb           # the Debian package in dist/ (needs build-essential, dpkg-dev and debhelper)
make python-dist   # wheel and sdist in dist/
```

A fresh clone needs only `make check`, which creates the virtual environment on its own. Contribution rules: [CONTRIBUTING.md](CONTRIBUTING.md).

## License

AGPL-3.0-or-later. Copyright (C) 2026 Florian Punz. See [LICENSE](LICENSE) and [ADR 0015](docs/adr/0015-license.md).
Some test fixtures come from the test data of other projects and keep their own licenses; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Affiliation

This is an independent project. It is not affiliated with or endorsed by Proxmox Server Solutions GmbH. Proxmox is a registered trademark of Proxmox Server Solutions GmbH. The name of the platform is used only to say what the tool is for.
