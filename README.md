<img alt="pve-smart-alert" src="docs/img/banner.png" />

<h1 align="center">PVE SDA</h1>

`pve-smart-alert` checks the SMART data of every drive in a Proxmox VE host at regular intervals and reports problems through the Proxmox VE notification system.

> **Status: early development.** No drive is read yet.
>
> <details>
> <summary>In progress: M2, drive discovery and collection</summary>
>
> - **M0 (done):** development tooling
> - **M1 (done):** the notification route (two transports and the Perl bridge), the two commands below and the Debian package that ships them
> - **M2 (in progress):** discovery and collection for SATA and NVMe drives; the routing check is built, the rest of M2 follows
> - **M3 (planned):** evaluation and configuration
> - **M4 (planned):** state and notification policy
> - **M5 (planned):** packaging, timer and installation
> - **M6 (planned):** SAS and hardware RAID on recorded data
> - **M7 (planned):** hardening, documentation and version 1.0, the version meant for regular use
>
> </details>

## Planned features

- **Automatic discovery:** finds all SATA, SAS and NVMe drives, including drives behind hardware RAID controllers that smartctl can reach
- **Predictive thresholds:** judges drives by thresholds that predict failure instead of merely confirming it
- **No repeat alerts:** reports a problem once, and again only when it gets worse or a reminder is due
- **Real severities:** sends messages through the targets and matchers configured under Datacenter → Notifications
- **Simple operation:** installs with one command and runs without care afterwards
- **Read-only:** only reads from drives and changes nothing on the host except its own files

## Installation

There is no release yet. `make deb` builds the package into `dist/` on a Debian or Proxmox VE host with build-essential, dpkg-dev and debhelper. Copy it to each node and install it there as root:

```sh
apt install ./pve-smart-alert_*_all.deb
```

- On a Proxmox VE 9 host it pulls in no other package. `apt purge pve-smart-alert` removes it together with its configuration and state.
- The configuration is `/etc/pve-smart-alert/config.toml`. `/usr/share/doc/pve-smart-alert/config.reference.toml` lists every key with its default.
- Only `transport` in `[notify]` has an effect so far: `auto` (default) sends through the notify bridge with mail to root as the fallback, `pve-notify` through the bridge only, `mail` as mail to root only. The keys of `[smartctl]` and `[[discovery.device]]` are validated, but nothing uses them while no drive is read.

## Commands

The installed tool has two commands:

| Command | Does |
| --- | --- |
| `pve-smart-alert doctor` | Reports one line per part of the host the tool works with: configuration, notify bridge, templates, mail command, and the routing of notifications and of the fallback mail to root (FR-603). A last line names what it does not check yet |
| `pve-smart-alert test-notification` | Sends one test notification, prints what the notification system did with it and names the matchers that route it (FR-520) |

Options of `test-notification`:

- `--severity SEVERITY`: `info` (default), `notice`, `warning` or `error`
- `--transport TRANSPORT`: `auto`, `pve-notify` or `mail`, as for `transport` in the configuration; without the option the configuration decides.

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
- [docs/check-catalog.md](docs/check-catalog.md): planned checks and default thresholds
- [docs/adr/](docs/adr/README.md): one record per architecture decision
- [docs/research/](docs/research/README.md): evidence behind the decisions, with sources
- [ROADMAP.md](ROADMAP.md): milestones, each with a testable result, and the state of each
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

## Affiliation

This is an independent project. It is not affiliated with or endorsed by Proxmox Server Solutions GmbH. Proxmox is a registered trademark of Proxmox Server Solutions GmbH. The name of the platform is used only to say what the tool is for.
