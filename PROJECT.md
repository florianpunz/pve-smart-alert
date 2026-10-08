# PVE SMART Alert

SMART drive alerts for Proxmox VE.

This document describes what the project is for and what version 1 contains. How far the work is: [ROADMAP.md](ROADMAP.md).

## Purpose

PVE SMART Alert is a small tool for Proxmox VE hosts.
It reads the SMART data of every drive in the host at regular intervals, decides whether a drive has a problem or is getting worse, and sends a message through the central notification system of Proxmox VE (targets and matchers under Datacenter → Notifications).

It covers:

- directly attached SATA, SAS and NVMe drives,
- drives that are members of ZFS pools, md arrays or LVM volume groups,
- drives behind hardware RAID controllers that are only reachable through a pass-through option of smartctl, such as MegaRAID and HPE Smart Array.

## Goals

1. **Installation with one command.** After that it runs without care.
2. **Automatic discovery.** No drive has to be configured.
3. **Sensible default thresholds** that can be overridden in a configuration file.
4. **No alert flood.** A problem is reported once, and again only when it gets worse or when a configurable reminder interval has passed.
5. **Messages that answer the first questions immediately:** which host, which drive (model, serial number, device and location), which value, how bad.
6. **The same behavior on a single host and on every node of a cluster.**

## Principles

- **Read-only.** The tool changes nothing on the host except its own files, and it only reads from drives. It does not enable SMART, start self-tests or touch smartd.
- **No extra dependencies.** It uses what a Proxmox VE host already has: Python, Perl, smartmontools.
- **Transparent decisions.** Every alert names the check, the value and the threshold. Every check can be adjusted or switched off, globally or for one drive.
- **Fail loudly.** If the tool cannot do its job (smartctl missing, configuration broken, notification route down), that is itself reported.
- **Honest hardware support.** Each controller family is labeled by how it was verified.

## Audience

- Administrators of single Proxmox VE hosts and small to medium clusters who do not run a separate monitoring system, or who want drive alerts in the same place as their backup and replication alerts.
- Homelab users who want more than smartd's defaults without operating a dashboard.
- Administrators of hosts with hardware RAID controllers, for whom the Proxmox VE web interface shows no SMART data at all.

It is not aimed at organizations that already monitor drives with Zabbix, Checkmk, Prometheus or similar. Their systems do this well.

## What exists already, and where PVE SMART Alert differs

Details and sources are in [docs/research/02-builtin-smart-handling.md](docs/research/02-builtin-smart-handling.md) and [docs/research/05-prior-art.md](docs/research/05-prior-art.md).

| Existing solution | What it does | Where it stops |
| --- | --- | --- |
| **smartd**, as shipped with Proxmox VE | Mails `root` when the drive's own health verdict fails, when pending or uncorrectable sectors are non-zero, and when error or self-test logs grow | No thresholds on the counters that predict failure, no wear or spare monitoring, no severity (every mail is `system-mail` / `unknown`), daily repetition, tuning only by editing `smartd.conf` per drive |
| **Proxmox VE web interface** | Shows a health verdict and a wear-out value on demand | Evaluates and alerts on nothing; shows nothing for drives behind RAID controllers |
| **Scrutiny** | Dashboard with history and thresholds from real-world failure rates | A web application with database and containers to operate; alerts through its own channels |
| **Prometheus smartctl_exporter, Zabbix, Checkmk, check_smart** | SMART checks inside a monitoring system | Need that monitoring system |
| **Community scripts** | One-off reports, or small scripts that mail `root` | No state, no repeat suppression, no RAID pass-through, no severity |

PVE SMART Alert is the piece in between: a host-local tool with nothing to operate, with thresholds that mean something, with memory, and with delivery into the notification system that Proxmox VE administrators already configure.

## Scope of version 1

Decided in [ADR 0017](docs/adr/0017-scope-of-version-1.md).

In:

- Proxmox VE 9.x, single host or cluster node.
- SATA, SAS and NVMe drives, directly attached.
- MegaRAID family through automatic discovery. HPE Smart Array through probing, labeled experimental. Any other pass-through type through manual device entries.
- The check catalog in [docs/check-catalog.md](docs/check-catalog.md): the drive's own verdict, defect and error counters, wear and spare, temperature, self-test results, missing and unreadable drives.
- Notification policy: once, on escalation, on worsening, on reminder, on recovery; grouping per drive; one summary on the first run.
- Notifications with severity and metadata through the Proxmox VE notification system, with mail to `root` as automatic fallback.
- One configuration file with global and per-drive overrides.
- Commands for checking, status, device listing, self-diagnosis, test notifications and recording test data.
- A Debian package, a systemd timer and a one-command installation.

Out:

- The state of pools, arrays and logical volumes. ZED, mdadm and vendor tools cover that.
- Starting or scheduling self-tests.
- Any change to smartd.
- A web interface, metrics export, history and trend prediction.
- An APT repository (first milestone after 1.0).
- Controllers that smartmontools cannot query (`mpi3mr`).
- Proxmox VE 8, Proxmox Backup Server, plain Debian.

## Risks

| Risk | Handling |
| --- | --- |
| The notification route with severity uses an internal Proxmox VE interface that may change | Isolated in one small file, checked on every run, automatic fallback to the documented mail route ([ADR 0008](docs/adr/0008-notification-integration.md)). Verified first, in milestone M1 |
| Hardware RAID cannot be tested on real hardware by the maintainer | Recorded output, a fake smartctl, a fixture recording command for users, and evidence labels ([ADR 0016](docs/adr/0016-test-strategy.md)) |
| Default thresholds may be too noisy or too quiet | Founded on published failure rates where they exist, marked provisional, overridable per drive ([ADR 0010](docs/adr/0010-health-evaluation-and-default-thresholds.md)) |
| Proxmox VE plans a health-check framework that includes disk state and notifications | No design or date is public. PVE SMART Alert stays small and can integrate or retire when it arrives. Tracked in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) |
| SMART does not predict every failure | Documented plainly. Missing and unreadable drives are detected separately. The tool is not a substitute for redundancy and backups |

## Project documents

| Document | Content |
| --- | --- |
| [CLAUDE.md](CLAUDE.md) | Binding rules for everyone working in the repository |
| [REQUIREMENTS.md](REQUIREMENTS.md) | Numbered functional and non-functional requirements |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, run sequence, configuration, state, notification, error handling |
| [ROADMAP.md](ROADMAP.md) | Milestones with testable results, and the state of each |
| [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) | What could not be settled |
| [docs/adr/](docs/adr/README.md) | One record per decision |
| [docs/research/](docs/research/README.md) | Evidence behind the decisions, with sources |
| [docs/check-catalog.md](docs/check-catalog.md) | Checks and default thresholds |

## Name, home and affiliation

- Name: `pve-smart-alert` for the repository, the package and the command. In running text: PVE SMART Alert ([ADR 0018](docs/adr/0018-project-name.md)). The working name during planning was PVE-SDA.
- Home: <https://github.com/florianpunz/pve-smart-alert> ([ADR 0019](docs/adr/0019-repository-hosting.md)).
- Maintainer and copyright holder: Florian Punz.
- License: AGPL-3.0-or-later ([ADR 0015](docs/adr/0015-license.md)), confirmed by the maintainer.
- The project is independent. It is not affiliated with or endorsed by Proxmox Server Solutions GmbH. Proxmox is a registered trademark of that company. The name of the platform is used only to say what the tool is for.
