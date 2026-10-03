# ADR 0017: Scope of version 1

- Status: Accepted
- Date: 2026-10-03

## Context

The project description is broad: all drives, three kinds of RAID, automatic discovery, sensible thresholds, no flood, clear messages, single hosts and clusters.
Version 1 must be small enough to finish and to trust, and complete enough to replace a hand-written smartd configuration for its users.
The maintainer can test SATA SSDs and NVMe drives on a real cluster. Everything else can only be tested through recorded output ([ADR 0016](0016-test-strategy.md)).

## Options considered

1. **Minimal**: directly attached SATA and NVMe only, mail to root only.
   Quick, but it leaves out the two things that distinguish the project: severity in the notification system and drives behind controllers.
2. **Everything in the description, fully supported.**
   Would claim support for hardware nobody on the project has seen.
3. **Complete core, honest labels**: everything needed for directly attached drives and for MegaRAID is in and tested; anything that cannot be verified is in as experimental or reachable through manual configuration; comfort features wait.

## Decision

Option 3.

### In version 1

| Area | Content |
| --- | --- |
| Platform | Proxmox VE 9.x, single host or any node of a cluster |
| Drives | SATA, SAS and NVMe, directly attached, including members of ZFS pools, md arrays and LVM volume groups |
| Hardware RAID | MegaRAID family through automatic discovery (verified by fixtures). HPE Smart Array through probing (experimental). Any other pass-through type through manual device entries |
| Evaluation | The check catalog of [ADR 0010](0010-health-evaluation-and-default-thresholds.md) for ATA, NVMe and SCSI, missing and unreadable drives |
| Policy | Everything in [ADR 0009](0009-notification-policy.md): once, escalation, worsening, reminders, recovery, grouping, first-run summary, tool-level conditions |
| Notification | `PVE::Notify` with severity and metadata, mail to root as fallback, plain-text messages |
| Configuration | One TOML file with global and per-drive overrides, validation, last-good fallback |
| Commands | `check`, `status`, `scan`, `doctor`, `test-notification`, `config check`, `config show`, `dump-fixture` |
| Operation | systemd timer, journal logging, failure unit |
| Distribution | Debian package on the release page, one-command installation |
| Documentation | README, configuration reference, check catalog, hardware support table with evidence labels, coexistence with smartd, troubleshooting, manual page |

### Explicitly not in version 1

| Item | Reason | Where it goes |
| --- | --- | --- |
| State of pools, arrays and logical volumes | Different problem with existing tools (ZED, mdadm, vendor utilities) | Not planned |
| Scheduling or starting self-tests | Would end the read-only rule ([ADR 0012](0012-read-only-and-coexistence-with-smartd.md)) | Needs its own decision |
| Changing smartd | Host footprint rule | Not planned. The maintainer's answer is in the [index of decision records](README.md) |
| Web interface, integration into the Proxmox VE GUI | Out of proportion; would mean patching Proxmox VE | Not planned |
| Metrics export, history, trend graphs | Scrutiny and the Prometheus exporter do this well | Possibly a text-file export later |
| Rate-based checks and failure prediction | Need history | After version 1 |
| `ack` command for known conditions | Per-drive overrides cover the need | After version 1 |
| HTML notification template | Plain text is rendered acceptably by Proxmox VE | After version 1 |
| APT repository | Needs signing and hosting decisions | First milestone after 1.0 |
| Cluster-wide configuration and cluster-wide status view | Needs a design that does not depend on pmxcfs for operation | After version 1 |
| Bay numbers through vendor tools | Vendor tools are not installed by default | After version 1, optional |
| Controllers using `mpi3mr` | Not supported by smartmontools | Depends on upstream |
| Ceph-specific context | Ceph has its own device health tracking | Not planned |
| Proxmox Backup Server, plain Debian | Different notification system | On demand |
| Proxmox VE 8 | End of life | Not planned |
| Drives attached through USB bridges | Often no SMART pass-through, frequently removed | Monitored if smartctl can read them, exempt from missing detection; no further effort |

### Release criteria for 1.0

- All requirements marked for version 1 in `REQUIREMENTS.md` are met and have a passing test or a completed acceptance step.
- The acceptance checklists of all milestones were run on the maintainer's cluster.
- At least one MegaRAID scenario built from real recorded output passes.
- Installation, upgrade from the previous pre-release, and purge were tested on a current Proxmox VE 9 host.
- The open questions that affect correctness are closed or documented as known limitations.

## Consequences

- Version 1 is useful on the maintainer's own cluster from the milestone that adds the timer, well before 1.0.
- Hardware RAID users get a tool that is honest about what was tested, and a way to help by contributing recordings.
- Several attractive features are postponed. The roadmap lists them so that the scope does not creep.
- The public interface that version 1 freezes is small: command names, configuration keys, check identifiers and notification fields.

## Revisit when

- A milestone shows that an item in scope cannot be done as planned.
- Proxmox VE's planned health-check framework appears and changes what is worth building.
