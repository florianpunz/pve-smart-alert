# Research notes

These notes record what was checked before the architecture decisions were taken, where it was checked, and for which versions it holds.
The ADRs in [`../adr/`](../adr/) refer to them instead of repeating the evidence.

| Note | Question |
| --- | --- |
| [01 Notification integration](01-notification-integration.md) | How can an external tool feed a message into the Proxmox VE notification system? |
| [02 Built-in SMART handling](02-builtin-smart-handling.md) | What does Proxmox VE already do, where is the gap, and how are duplicate alerts avoided? |
| [03 SMART indicators and smartctl JSON](03-smart-indicators.md) | Which values predict failure, and how do SATA, SAS and NVMe differ in `smartctl --json`? |
| [04 Hardware RAID](04-hardware-raid.md) | How are drives behind RAID controllers found, and which controllers are realistic? |
| [05 Prior art](05-prior-art.md) | Which existing projects solve something similar, and what follows for PVE SMART Alert? |
| [06 Recordings from the test cluster](06-test-cluster-recordings.md) | What do the drives, the wear values and the matcher configuration of the test cluster look like? Recorded 2026-10-05 |

## Scope of validity

- Research date: 2026-10-03.
- Proxmox VE documentation: version 9.2.13 (built 2026-09-24).
- Proxmox source code: `master` branch of the repositories on `git.proxmox.com` on the research date.
- smartmontools: manual pages of version 7.4 as packaged in Debian 13 (trixie), release notes of 7.3 to 7.5.
- Proxmox VE 9.2 was released on 2026-05-21. Proxmox VE 8 reached its end of life in 2026-08 according to the Proxmox VE FAQ, so Proxmox VE 9.x is the only supported major version at the time of writing.

Statements about older versions are marked as such.

## Confidence labels

Every claim in the notes carries one of these labels where it matters:

- **Verified**: read in the cited documentation or source code on the research date.
- **Reported**: stated by a third party (forum post, issue tracker); plausible, not checked on a real system.
- **Assumed**: based on general knowledge; not checked. Every assumption that matters for the design is tracked in [`OPEN-QUESTIONS.md`](../../OPEN-QUESTIONS.md).

Nothing in these notes was tested on a running Proxmox VE host. The first roadmap milestones exist to replace "Reported" and "Assumed" with test results.
