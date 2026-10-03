# ADR 0018: Project name `pve-smart-alert`

- Status: Accepted
- Date: 2026-10-03
- Decided by: the maintainer

## Context

The project was planned under the working name PVE-SDA, short for "Proxmox VE S.M.A.R.T. Disk Alert", with `pve-sda` as the package and command name.

The name is more than a label. It becomes the Debian package name, the command, the directories under `/etc` and `/var/lib`, the names of the systemd units, the name of the notification template, and the value of the notification field `type` that administrators write into their matchers ([ADR 0008](0008-notification-integration.md)). Changing it after the first release breaks routing rules and upgrade paths. Changing it during planning costs one search and replace.

Problems found with the working name:

- **It reads like a device name.** `sda` is the first SCSI disk on Linux. A subject such as "[PVE-SDA] WARNING pve1: /dev/sdb ..." looks contradictory at first glance.
- **It cannot be found.** A search for "pve sda" or "proxmox sda" returns discussions about the device `/dev/sda`.
- **The acronym says nothing** to someone who has not read its expansion.
- **The expansion starts with "Proxmox VE".** The brand guidelines of Proxmox say that the trademark is not authorized for use in product or app names. They give "Proxmox XY App" as the wrong form and "XY App for Proxmox Virtual Environment" as the right one. The abbreviation "PVE" is not mentioned there, and it is a common prefix of community tools.

This record is an engineering decision, not legal advice.

## Options considered

| Name | For | Against |
| --- | --- | --- |
| `pve-sda` (keep) | Short. Already used in all documents | Device-name confusion, not searchable, opaque acronym |
| `pve-smart-alert` | Says what the tool does. Contains the term people search for. No confusion with a device | Longer to type. "smart" can be read as an adjective |
| `pve-smart-notify` | Stresses the link to the notification system | Sounds like a general notification tool |
| `pve-drive-alert` | No acronym at all | Loses the term SMART. Disk and drive alerts are commonly understood as disk space alerts; a capacity monitor named `pve-guest-disk-alert` already exists |
| `pvesmart` | Shortest | Looks like one of Proxmox VE's own tools (`pvesm`, `pvecm`, `pvesh`) |

A web search on the decision date found no existing project named `pve-smart-alert`, `pve-smart-notify` or `pve-drive-alert`. This is not an exhaustive check.

## Decision

- The name is **`pve-smart-alert`**. It is used for the repository, the Debian package, the command, the Python package (`pve_smart_alert`), the directories (`/etc/pve-smart-alert`, `/var/lib/pve-smart-alert`, `/run/pve-smart-alert`), the systemd units, the notification template, and the value of the notification field `type`.
- In running text the project is written **PVE SMART Alert**.
- The one-line description is "SMART drive alerts for Proxmox VE".
- "Proxmox" is never part of the product name. The platform is named descriptively, in the form "for Proxmox VE".
- The README states that the project is not affiliated with or endorsed by Proxmox Server Solutions GmbH and that Proxmox is a registered trademark of that company.

Editorial note: the working name was replaced in all project documents, including the records 0001 to 0017 that were already accepted. No decision in those records changed.

## Consequences

- Notifications carry `type=pve-smart-alert`. A matcher uses the regex `^pve-smart-alert$`.
- The command is longer. It is typed rarely, because the timer runs the check.
- Search engines can find the project by what it does.
- The working name survives in two places outside the repository: the name of the maintainer's local folder and the name of the planning workspace. Neither is part of the product.
- If Proxmox ever objects to the prefix, the name has to change again. The risk is judged small, given how common the prefix is among community projects, and smaller than with a name that contains "Proxmox".

## Revisit when

- Proxmox publishes guidance on the abbreviation "PVE" in the names of third-party projects.
- An official Proxmox package with a conflicting name appears.

## Sources

- Proxmox media resources and brand guidelines: <https://www.proxmox.com/en/about/company-details/media-kit>
- `pve-guest-disk-alert`: <https://github.com/KittDoesntCode/pve-guest-disk-alert>
