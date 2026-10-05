# PVE SMART Alert

SMART drive alerts for Proxmox VE: `pve-smart-alert` checks the SMART data of every drive in a Proxmox VE host at regular intervals and reports problems through the Proxmox VE notification system.

> **Status: early development.** Milestones M0 and M1 are done: the development tooling, the notification route with its two transports and the Perl bridge, the two commands below, and the Debian package that ships them. No drive is read yet — discovery and collection arrive with milestone M2. The version meant for regular use is planned as 1.0 in M7.

## What works today

`make build` produces the Debian package, which installs the tool together with two commands:

| Command | Does |
| --- | --- |
| `pve-smart-alert test-notification [--severity SEVERITY] [--transport TRANSPORT]` | Sends one test notification and prints what the notification system did with it (FR-520). |
| `pve-smart-alert doctor` | Reports one line per part of the host the tool works with: the configuration, the notify bridge, the templates and the mail command (FR-603). |

The severity is `info`, `notice`, `warning` or `error` and defaults to `info`. The transport is `auto`, `pve-notify` or `mail`; without the option the configuration decides, and `auto` means the notify bridge with mail to root as the fallback.

## Routing

The notifications carry the type `pve-smart-alert`. They reach a target only if a matcher under Datacenter → Notifications matches them. With the unchanged default matcher this is the case without any setup. If the default matcher has been restricted, for example to the types `vzdump` and `system-mail`, the notifications are accepted and then dropped without an error. Add a matcher with the rule `type` as regex `^pve-smart-alert$` and the target you want. In the web interface this is Datacenter → Notifications → Notification Matchers → Add. On the command line, as root on one node:

```sh
pvesh create /cluster/notifications/matchers \
  --name pve-smart-alert \
  --target <TARGET> \
  --match-field 'regex:type=^pve-smart-alert$' \
  --match-severity info,notice,warning,error
```

Replace `<TARGET>` with the name of a target, as shown by `pvesh get /cluster/notifications/targets`. Route all four severities: the tool also sends `info` messages, for recoveries and for the first summary, and `notice` findings. A matcher that leaves out a severity drops those messages, and `pve-smart-alert doctor` reports the routing as `warn` from milestone M2 on. Then check the routing with `pve-smart-alert test-notification --severity warning`. A test that reports "Delivered: yes" with an empty log has only been accepted; look at the target to see whether it arrived.

## What it will do

- Find all SATA, SAS and NVMe drives by itself, including drives behind hardware RAID controllers that smartctl can reach.
- Judge them with thresholds that predict failure instead of merely confirming it.
- Report a problem once, and again only when it gets worse or when a reminder is due.
- Send messages with a real severity through the targets and matchers configured under Datacenter → Notifications.
- Install with one command and run without care afterwards.
- Change nothing on the host except its own files, and only read from drives.

## Documents

| Document | Content |
| --- | --- |
| [PROJECT.md](PROJECT.md) | Purpose, audience, comparison with existing solutions, scope of version 1 |
| [REQUIREMENTS.md](REQUIREMENTS.md) | Numbered, verifiable requirements |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, run sequence, configuration, state, notification, error handling |
| [ROADMAP.md](ROADMAP.md) | Milestones, each with a result that can be tested |
| [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) | What is not settled yet |
| [docs/adr/](docs/adr/README.md) | One record per architecture decision |
| [docs/research/](docs/research/README.md) | The evidence behind the decisions, with sources |
| [docs/check-catalog.md](docs/check-catalog.md) | Planned checks and default thresholds |
| [CLAUDE.md](CLAUDE.md) | Binding rules for contributors and AI agents |

## Development

Requirements: Python 3.11 or later, GNU Make and git.

```sh
make check         # lint, format check, type check, repository rules and tests
make dev-install   # create the virtual environment and install the development tools
make test          # the test suite
make build         # the Debian package and the Python distribution
make deb           # the Debian package in dist/ (needs build-essential, dpkg-dev and debhelper)
make python-dist   # wheel and sdist in dist/
```

`make check` creates the virtual environment on its own, so a fresh clone needs only that one command.
[CONTRIBUTING.md](CONTRIBUTING.md) describes the rules for contributions.

## License

AGPL-3.0-or-later. Copyright (C) 2026 Florian Punz. See [LICENSE](LICENSE) and [ADR 0015](docs/adr/0015-license.md).

## Affiliation

This is an independent project. It is not affiliated with or endorsed by Proxmox Server Solutions GmbH. Proxmox is a registered trademark of Proxmox Server Solutions GmbH. The name of the platform is used only to say what the tool is for.
