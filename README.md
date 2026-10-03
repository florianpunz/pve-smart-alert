# PVE SMART Alert

SMART drive alerts for Proxmox VE: `pve-smart-alert` checks the SMART data of every drive in a Proxmox VE host at regular intervals and reports problems through the Proxmox VE notification system.

> **Status: planning.** There is no code and nothing to install yet. This repository currently contains the project plan.

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

## License

AGPL-3.0-or-later. Copyright (C) 2026 Florian Punz. See [ADR 0015](docs/adr/0015-license.md). The license file is added with the first milestone.

## Affiliation

This is an independent project. It is not affiliated with or endorsed by Proxmox Server Solutions GmbH. Proxmox is a registered trademark of Proxmox Server Solutions GmbH. The name of the platform is used only to say what the tool is for.
