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
| [0022](0022-fallback-routing-check.md) | Check the route of the fallback, mail to root, as well | Accepted | How the tool detects that its fallback mail would be dropped |
| [0023](0023-anonymization-of-recordings.md) | Anonymize recordings with counters per archive | Accepted | Which values of a recording identify a drive and what replaces them |
| [0024](0024-drive-selectors.md) | Select drives by model pattern, serial number and WWN | Accepted | What the selectors of exclude rules and per-drive overrides mean |
| [0025](0025-sandboxing-of-the-check-service.md) | Sandboxing options of the check service | Accepted | Which systemd options restrict the check without breaking drives, mail or notification targets |
| [0026](0026-recordings-of-scsi-drives-and-of-other-projects.md) | Anonymize the names of SCSI drives, and import the test data of other projects | Accepted | How logical unit ids and SAS addresses are anonymized, and which recordings of other projects become fixtures |
| [0027](0027-pre-release-versions-for-test-builds.md) | Pre-release versions for test builds | Accepted | Which version a build for a test host carries until its release |
| [0028](0028-logical-volumes-and-enclosures.md) | Recognize logical volumes and enclosures by structured fields first | Accepted | How discovery tells a RAID logical volume and an enclosure from a drive, and what the location of a drive behind MegaRAID is |
| [0029](0029-notification-field-device-id.md) | The notification field `device-id` for drives behind a controller | Accepted | Which field lets a matcher select one drive behind a RAID controller, and when it is present |
| [0030](0030-controllers-whose-drives-cannot-be-queried.md) | Detect controllers whose drives cannot be queried from the driver of the SCSI host | Accepted | Which controllers `scan`, `doctor` and `tool.unsupported_controller` report, and which drivers they never report |
| [0031](0031-switching-tool-conditions-off.md) | Switch a condition of the tool off, and name the monitored drives of the notice | Accepted | The key that switches a condition of the tool off, and what the notice about an unsupported controller names |
| [0032](0032-hpe-smart-array-probe.md) | Probe the drives behind an HPE Smart Array controller | Accepted | The scope of the `cciss,N` probe, the node it reads, when it stops, the key that switches it off, its `device-id` and its standby check |
| [0034](0034-manual-entries-of-other-pass-through-types.md) | Drives behind the other RAID controllers | Accepted | That a drive behind Areca, 3ware, Adaptec, HighPoint or SSSRAID takes nothing lsblk shows for its node and is not woken in standby, that the JMicron types never reach smartctl, and that these types have no `device-id` in version 1 |

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

## Notes on accepted records

Where an accepted record has become outdated in a way that matters, without a change of its decision, the note is recorded here and the record stays as it is.

| Record | Note |
| --- | --- |
| [0002](0002-supported-platforms-and-version-baseline.md), [0004](0004-smartctl-json-as-data-source.md) | Proxmox VE 9.2 ships smartmontools 7.5, not 7.4 ([Research 06](../research/06-test-cluster-recordings.md)). 7.4 remains the version to support for older 9.x hosts |
| [0008](0008-notification-integration.md) | The test command alone does not make "no matcher matched" visible: the notification system accepts such a notification without an error and without a log line. The routing check of [0020](0020-routing-check.md) does |
| [0014](0014-repository-structure.md) | The layout tree is a snapshot of 2026-10-04; the repository itself shows the current layout. Commit messages now start with a type prefix such as `feat:` or `docs:`, as [CONTRIBUTING.md](../../CONTRIBUTING.md) describes |

## Adding a record

1. Copy the section structure of an existing record.
2. Use the next free number and a short title in the file name.
3. Set the status to `Proposed`, or to `Accepted` if the decision is already taken.
4. Add a row to the table above.
5. If the record replaces an older one, set the older record's status to `Superseded by NNNN`.
