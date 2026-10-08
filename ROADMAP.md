# Roadmap

Milestones towards version 1.0 of PVE SMART Alert and the planned steps after it.
Scope: [ADR 0017](docs/adr/0017-scope-of-version-1.md). Requirements: [REQUIREMENTS.md](REQUIREMENTS.md).

## State

| Milestone | State |
| --- | --- |
| M0: Repository bootstrap | Done, except that the repository is still private |
| M1: Walking skeleton with notifications | Done |
| M2: Discovery and collection for SATA and NVMe | In progress |
| M3 to M7 | Planned |

The section of a milestone says what of it is done and what comes next.

## How the milestones are ordered

1. **Riskiest assumption first.** The notification route with severity uses an internal interface of Proxmox VE. It is verified on a real host in M1, before anything is built on top of it.
2. **A package from the start.** From M1 on, every milestone is installed on the test cluster as a Debian package, never by copying files. Packaging problems show up early, and the host is never touched outside the package.
3. **Real hardware before simulated hardware.** SATA SSDs and NVMe drives on the maintainer's cluster come first (M2 to M5). SAS and hardware RAID follow on recorded data (M6).
4. **Useful early.** After M5 the tool monitors the maintainer's cluster in daily operation. M6 and M7 widen and harden it.

Every milestone ends with a result the maintainer can test on the cluster, and with these housekeeping steps: tests in CI are green, documents are updated, answered items are removed from [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md), and a decision that changed gets a new record.

Size is a rough relative estimate: S, M, L.

## Test environment

As stated by the maintainer on 2026-10-03:

- A Proxmox VE 9.2 high-availability cluster (9.2.21 at the time of planning), which is the current release line.
- SATA SSDs and NVMe drives, some of them used for LVM-thin.
- No hardware RAID controller.
- No disks or controllers passed through to guests, no drives attached through USB, no hard disks that spin down.

Recorded on 2026-10-05 ([Research 06](docs/research/06-test-cluster-recordings.md)): the nodes `pve5`, `pve6` and `pve7` with Proxmox VE 9.2.21 and smartmontools 7.5; three SATA SSDs from Samsung and Fanxiang and three NVMe drives from Samsung and Western Digital, all with LVM-thin, no ZFS. The USB device on `pve5` is the virtual drive of a KVM-over-IP device for mounting ISO images; it is not a monitored drive and plays no part in the acceptance steps.

What follows from this:

- SAS drives, hardware RAID, standby handling and false "missing" alerts caused by pass-through can only be tested with recorded data and simulation ([ADR 0016](docs/adr/0016-test-strategy.md)).
- The acceptance tests run on the current release line. If a newer 9.x release appears during development, the cluster follows it.

## M0: Repository bootstrap (S)

Goal: a repository in which work can start.

Deliverables:

- The public repository `github.com/florianpunz/pve-smart-alert` ([ADR 0019](docs/adr/0019-repository-hosting.md)).
- Directory layout of [ADR 0014](docs/adr/0014-repository-structure.md), `LICENSE`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.
- `pyproject.toml` with linter, formatter and type checker configuration. `Makefile` with `check`, `test`, `build`.
- CI on GitHub Actions: lint, type check and tests on Python 3.11, 3.13 and the newest release; a check that no file carries AI attribution and that source files have an SPDX line.
- An empty Python package with a `pve-smart-alert --version` command and one test.

Result you can test:

- In a fresh clone, `make check` passes.
- CI is green on the default branch.

Inputs, all settled: the name `pve-smart-alert` ([ADR 0018](docs/adr/0018-project-name.md)), the repository location ([ADR 0019](docs/adr/0019-repository-hosting.md)), the copyright holder Florian Punz, and the license AGPL-3.0-or-later ([ADR 0015](docs/adr/0015-license.md)).

State: done on 2026-10-04, except that the repository is still private. The reporting channel of [SECURITY.md](SECURITY.md), a private security advisory on GitHub, works only once the repository is public: GitHub offers private vulnerability reporting for public repositories only, and it has to be enabled in the settings of the repository.

## M1: Walking skeleton with notifications (M)

Goal: prove the notification route on a real host, with a real package.

Deliverables:

- The Perl notify bridge, the two template files, the `pve-notify` and `mail` transports with automatic fallback ([ADR 0008](docs/adr/0008-notification-integration.md)).
- Commands `pve-smart-alert test-notification` and a first `pve-smart-alert doctor`.
- A minimal Debian package that installs these parts, built by `make build`.
- Bridge contract test against a stub of `PVE::Notify`.

Result you can test, on one cluster node:

1. `apt install ./pve-smart-alert_0.1.0_all.deb` installs without pulling in other packages.
2. `pve-smart-alert test-notification --severity warning` arrives through the default notification target with severity `warning`.
3. A matcher with `match-field regex:type=^pve-smart-alert$` and `match-severity warning,error` routes the test message to a second target, and a test with severity `info` does not reach it.
4. With the bridge made unusable on purpose (for example a renamed template file), the test message arrives as system mail, and its text says that the fallback was used.
5. `pve-smart-alert doctor` reports both situations correctly.
6. `apt purge pve-smart-alert` leaves no file behind.

Open questions this milestone answered: Q-N1 to Q-N3, Q-N7, and the part of Q-N5 about the web interface. Q-N4 and the rest of Q-N5 are left to M5.

Decision point: if the primary route cannot be made to work or to fail visibly, [ADR 0008](docs/adr/0008-notification-integration.md) is revised before M2 starts.

State: done. The acceptance run passed on the test cluster on 2026-10-04, on Proxmox VE 9.2, and ADR 0008 stands. The run showed one failure that ADR 0008 had not foreseen: a notification that no matcher matches is dropped without an error. [ADR 0020](docs/adr/0020-routing-check.md) answers it with the routing check of M2.

## M2: Discovery and collection for SATA and NVMe (M)

Goal: find and read every drive of the test cluster.

Deliverables:

- Discovery from the smartctl scan, enrichment, filtering, de-duplication, identity ([ADR 0005](docs/adr/0005-drive-discovery-and-identity.md)).
- Collector with timeout and standby handling; parsers for ATA and NVMe; snapshot model ([ADR 0004](docs/adr/0004-smartctl-json-as-data-source.md)).
- The configuration keys of `[smartctl]` (`path`, `timeout`, `detail`) and manual devices in `[[discovery.device]]` ([ADR 0011](docs/adr/0011-configuration.md)).
- Commands `pve-smart-alert scan` and `pve-smart-alert dump-fixture`.
- The fake smartctl and the first fixtures, made from the recordings of [Research 06](docs/research/06-test-cluster-recordings.md) and anonymized as [ADR 0023](docs/adr/0023-anonymization-of-recordings.md) describes.
- A line `smartctl` in `pve-smart-alert doctor`: present, version.
- The wear value from the sources of [ADR 0021](docs/adr/0021-wear-value-source.md), shown with its source.
- The routing check of [ADR 0020](docs/adr/0020-routing-check.md): a line `routing` in `pve-smart-alert doctor`, and the matching matchers in the output of `pve-smart-alert test-notification`. Fixtures recorded with `pvesh` from at least two matcher configurations, anonymized.
- The check of the fallback route of [ADR 0022](docs/adr/0022-fallback-routing-check.md): a line `fallback` in `pve-smart-alert doctor` for mail to root.

Result you can test, on every cluster node:

1. `pve-smart-alert scan` lists every physical drive exactly once, with the right model, serial number, class, and pool or volume group, and lists skipped devices with a reason.
2. The wear value shown for each SSD equals the "Wearout" column of the web interface, or `scan` names the vendor-neutral source that gives a different value ([ADR 0021](docs/adr/0021-wear-value-source.md)). On the test cluster this applies to the Fanxiang S301 on `pve5`: 44 % from the device statistics against 0 % in the web interface.
3. `pve-smart-alert dump-fixture --all` writes an archive that contains no real serial number.
4. With a drive name that does not exist as a manual entry, the scan still completes and reports that device as unreadable.
5. With the default matcher restricted so that it no longer matches the type `pve-smart-alert`, `pve-smart-alert doctor` reports `routing` as `warn`, names the severities that are not routed and says how to add a matcher. `pve-smart-alert test-notification` says that no matcher matched. With the matcher of M1 in place, which routes only `warning` and `error`, `doctor` reports `routing` as `warn` and names `info` and `notice`. With that matcher extended to `info,notice,warning,error`, both report the matching matcher and `doctor` reports `ok`. A severity of the tool that no matcher routes always means `warn`; this is how the rules for `ok` and `warn` in [ADR 0020](docs/adr/0020-routing-check.md) are read.

How to run it: install the new package on each node, run [`scripts/collect-node-data.sh`](scripts/collect-node-data.sh), which also records the output of `scan` and `doctor`, and check the steps against the archive. Steps 3, 4 and 5 and the test notification need the commands given there in addition. Since 2026-10-05 the matcher of the tool on the test cluster routes all four severities; for the `warn` case of step 5 it is set back to `warning,error` for the test.

Open questions this milestone answers: Q-S1 to Q-S4 and Q-N8.

State: in progress.

- Done: the preparation on 2026-10-05, that is the recordings of all three nodes and of three matcher configurations ([Research 06](docs/research/06-test-cluster-recordings.md)), the collection script and the decision on the wear source; the routing check, which passed step 5 on 2026-10-07 on `pve7` ([ARCHITECTURE.md](ARCHITECTURE.md) section 10); the line `fallback`, built after that run and not yet run on the cluster; the snapshot model; the configuration keys; the anonymizer and the fixtures of the three nodes.
- Next: the parsers for ATA and NVMe with the wear value, the collector, discovery, the fake smartctl, the commands `scan` and `dump-fixture`, and the line `smartctl` in `doctor`. Then steps 1 to 4 on every node.

## M3: Evaluation and configuration (M)

Goal: turn snapshots into findings with sensible, adjustable thresholds.

Deliverables:

- The check catalog for ATA and NVMe with defaults ([ADR 0010](docs/adr/0010-health-evaluation-and-default-thresholds.md), [docs/check-catalog.md](docs/check-catalog.md)).
- Configuration loading, validation, global and per-drive overrides, last-good fallback ([ADR 0011](docs/adr/0011-configuration.md)).
- Commands `pve-smart-alert check --dry-run`, `pve-smart-alert config check`, `pve-smart-alert config show`.
- Fixtures for degraded drives, taken from public test data or derived from real recordings, one per check and severity.
- Review of the provisional default thresholds against all fixtures collected so far.

Result you can test:

1. `pve-smart-alert check --dry-run` on each node lists the findings for the real drives. For healthy drives the list is empty.
2. With `smartctl.path` pointing at the fake smartctl and the scenario "failing-hdd", the dry run shows the expected findings with the expected severities.
3. A threshold changed in `config.toml` changes the result. A per-drive override that disables a check removes that finding for that drive only.
4. A deliberate typing error in `config.toml` is reported by `pve-smart-alert config check` with the key name, and the dry run still works with the previous configuration.

Open questions this milestone answers: Q-T1 to Q-T4.

## M4: State and notification policy (L)

Goal: the behavior that distinguishes the tool: once, on worsening, on reminder.

Deliverables:

- State store with atomic replacement, migration, corruption handling ([ADR 0007](docs/adr/0007-state-storage.md)).
- Notification planner with all rules of [ADR 0009](docs/adr/0009-notification-policy.md); renderer with the message layout of [ARCHITECTURE.md](ARCHITECTURE.md).
- Missing and unreadable drive detection, tool-level conditions.
- Commands `pve-smart-alert check` and `pve-smart-alert status`.
- Scenario tests for every rule, with an injected clock.

Result you can test, on one node, with the fake smartctl replaying a scenario step by step:

1. First run: exactly one summary notification arrives that lists all drives.
2. Second run without change: nothing arrives.
3. Step "3 pending sectors": one notification, severity warning, naming drive, value and threshold.
4. Same step again: nothing.
5. Step "20 pending sectors": one notification, severity error, marked as escalated.
6. Step "healthy again", twice: one recovery notification.
7. Step "drive gone", twice: one notification about the missing drive.
8. Scenario "five drives too hot": one summary notification instead of five.
9. `pve-smart-alert status` shows the active conditions at each step.
10. Deleting the state file leads to one summary on the next run, not to individual alerts.

After this milestone the real smartctl is configured again and `pve-smart-alert check` can be run by hand against the real drives.

## M5: Packaging, timer and installation (M)

Goal: one command, then no care.

Deliverables:

- Complete Debian package with units, failure reporter, reference configuration and maintainer scripts ([ADR 0013](docs/adr/0013-packaging-and-installation.md), [ADR 0006](docs/adr/0006-scheduling.md)). The manual page follows with the user documentation in M7.
- Release pipeline: build on tag, lintian, package test in a clean container, checksums, release assets under stable names, `install.sh`.
- Decision on which systemd sandboxing options are safe.

Result you can test:

1. The documented one-line command installs the tool on each cluster node.
2. Within a few minutes each node sends its first-run summary without any further action.
3. `systemctl list-timers pve-smart-alert.timer` shows the next run about 30 minutes later, and the journal shows one summary line per run.
4. After a reboot of a node, runs resume by themselves.
5. Installing a newer build keeps configuration and state; no first-run summary is sent again.
6. With the program made to crash on purpose, a mail from the failure reporter arrives, once.
7. `apt purge pve-smart-alert` removes everything; `dpkg -S` finds no leftover file, and `/etc/pve-smart-alert`, `/var/lib/pve-smart-alert` and the template files are gone.
8. A node that has lost quorum still runs its check and sends through the fallback if needed.

From here on the tool runs permanently on the maintainer's cluster. Version tag: 0.5.0.

Open questions this milestone answers: Q-N4, Q-N5 and Q-P1 to Q-P3.

## M6: SAS and hardware RAID on recorded data (L)

Goal: cover what the test cluster does not have.

Deliverables:

- Parser and checks for SCSI/SAS.
- MegaRAID handling: pass-through types, logical volumes and enclosures skipped, de-duplication in JBOD mode, changing device IDs.
- HPE Smart Array probe, experimental.
- Manual device entries for all other pass-through types.
- Detection and reporting of controllers that cannot be queried.
- Fixtures and scenarios for each case, with origin and license recorded.
- Hardware support table in the documentation with evidence labels ([ADR 0016](docs/adr/0016-test-strategy.md)).
- A documented way for users to contribute recordings, and a call for them.

Result you can test:

1. `make test` runs scenarios named after each controller family and passes.
2. On a cluster node, with the fake smartctl replaying the MegaRAID scenario, `pve-smart-alert scan` shows the physical drives behind the controller, skips the logical volume with a reason, and a degraded drive in the scenario produces a notification that names controller and device ID.
3. The same for a SAS drive scenario.
4. The hardware support table states for every family how it was verified.

Open questions this milestone answers or narrows: Q-R1 to Q-R5.

## M7: Hardening, documentation, release 1.0 (M)

Goal: a release that others can install with confidence.

Deliverables:

- User documentation: installation, configuration reference, check catalog, notification routing examples, coexistence with smartd, hardware support, troubleshooting, manual page.
- Review of the security points in [ARCHITECTURE.md](ARCHITECTURE.md), including handling of hostile strings in drive data.
- Review of all default thresholds and policy defaults against the experience from the maintainer's cluster since M5.
- All requirements checked off against tests or acceptance steps.
- Release notes, version 1.0.0.

Result you can test:

1. A second person, or the maintainer on a freshly installed Proxmox VE 9 host, gets from the README to the first-run summary without asking a question.
2. Every requirement in `REQUIREMENTS.md` has a passing test or a ticked acceptance step.
3. The tool has run on the cluster for at least four weeks without a false alert and without a failed run.
4. An upgrade from 0.5.x to 1.0.0 keeps configuration and state.
5. The acceptance checklists of M1 and M5 pass on the current Proxmox VE 9.x release, not only on the version the cluster ran during development.

## After 1.0

In the order that currently seems most useful. Each item gets its own plan when it is started.

| Item | What it adds |
| --- | --- |
| APT repository | Upgrades through normal system updates, signed packages |
| `pve-smart-alert ack` | Acknowledge a known condition from the command line until it gets worse, instead of editing the configuration |
| HTML notification template | Better-looking mail |
| Cluster-wide configuration | One file for all nodes, read from pmxcfs when available, overridden by the node file |
| Optional slot lookup through vendor tools | Enclosure and bay in notifications for RAID controllers |
| Rate-based checks | "More than N new defects per day"; needs a history store and a decision record |
| Text-file export | Current state as a file for existing metrics collectors |
| Further controller probes | Adaptec, Areca and others, as recordings arrive |
| Proxmox VE 10 | Compatibility release when the first beta is available |
| Proxmox Backup Server | A transport for its notification system, if there is demand |

Things that stay out of scope are listed in [ADR 0017](docs/adr/0017-scope-of-version-1.md).
