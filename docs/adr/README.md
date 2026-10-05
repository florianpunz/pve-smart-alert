# Architecture Decision Records

One record per decision, as described in [ADR 0001](0001-record-architecture-decisions.md).
An accepted record is not rewritten. A changed decision gets a new record that supersedes the old one.

| No. | Title | Status | Decides |
| --- | --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | How decisions are documented |
| [0002](0002-supported-platforms-and-version-baseline.md) | Supported platforms and version baseline | Accepted | Proxmox VE 9.x, Python 3.11 baseline, smartmontools 7.0 minimum |
| [0003](0003-implementation-language.md) | Python standard library plus a minimal Perl bridge | Accepted | Implementation language |
| [0004](0004-smartctl-json-as-data-source.md) | smartctl JSON output as the only source of drive data | Accepted | Where health data comes from and how smartctl is called |
| [0005](0005-drive-discovery-and-identity.md) | Drive discovery and drive identity | Accepted | How drives are found, filtered and identified |
| [0006](0006-scheduling.md) | Scheduling with a systemd timer, every 30 minutes | Accepted | Scheduling mechanism and interval |
| [0007](0007-state-storage.md) | State in a node-local JSON file | Accepted | Where and how state is kept |
| [0008](0008-notification-integration.md) | Notifications through `PVE::Notify`, with mail to root as fallback | Accepted | Connection to the Proxmox VE notification system |
| [0009](0009-notification-policy.md) | Notification policy: once, on worsening, and on reminder | Accepted | When a notification is sent and how notifications are grouped |
| [0010](0010-health-evaluation-and-default-thresholds.md) | Health evaluation model and default thresholds | Accepted | Check catalog, severities, default numbers |
| [0011](0011-configuration.md) | Configuration in a single TOML file | Accepted | Configuration format and failure behavior |
| [0012](0012-read-only-and-coexistence-with-smartd.md) | Read-only operation and coexistence with smartd | Accepted | Host and drive footprint, relation to smartd |
| [0013](0013-packaging-and-installation.md) | Debian package with a one-command installation | Accepted | Packaging, installation, file layout |
| [0014](0014-repository-structure.md) | Repository structure | Accepted | Directory layout and conventions |
| [0015](0015-license.md) | License AGPL-3.0-or-later | Accepted | License |
| [0016](0016-test-strategy.md) | Test strategy: recorded fixtures and a fake smartctl | Accepted | How the tool is tested without the hardware |
| [0017](0017-scope-of-version-1.md) | Scope of version 1 | Accepted | What is in version 1 and what is not |
| [0018](0018-project-name.md) | Project name `pve-smart-alert` | Accepted | Name of repository, package, command and notification type |
| [0019](0019-repository-hosting.md) | Repository on GitHub under the maintainer's account | Accepted | Where the project is hosted and released |
| [0020](0020-routing-check.md) | Check the routing of the notifications through the public API | Accepted | How the tool detects that no matcher matches |
| [0021](0021-wear-value-source.md) | Take the wear value from the vendor-neutral sources first | Accepted | Which source the wear value of an SSD comes from |

## Confirmed by the maintainer

The records 0001 to 0017 were accepted without individual sign-off, as agreed. On 2026-10-03 the maintainer reviewed the decisions that are hard to change later or that touch a rule he set:

| Record | Outcome |
| --- | --- |
| [0015](0015-license.md) | AGPL-3.0-or-later confirmed. Copyright holder: Florian Punz |
| [0008](0008-notification-integration.md) | Accepted that the package installs its two template files into the template directory of `pve-manager` |
| [0012](0012-read-only-and-coexistence-with-smartd.md) | smartd stays untouched. No command for quieting smartd in version 1; the documentation describes the manual steps |
| [0018](0018-project-name.md), [0019](0019-repository-hosting.md) | Decided by the maintainer |

Confirmations are recorded here and not in the records themselves, because accepted records are not rewritten.
Two kinds of editorial changes were made to accepted records on that day and changed no decision: the working name was replaced by the final name ([0018](0018-project-name.md)), and references in the records 0012, 0013, 0015 and 0017 to questions that were still open were redirected to where the answers are.

## Adding a record

1. Copy the section structure of an existing record.
2. Use the next free number and a short title in the file name.
3. Set the status to `Proposed`, or to `Accepted` if the decision is already taken.
4. Add a row to the table above.
5. If the record replaces an older one, set the older record's status to `Superseded by NNNN`.
