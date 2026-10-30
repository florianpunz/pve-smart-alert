# Roadmap

Milestones towards version 1.0 of PVE SMART Alert and the planned steps after it.
Scope: [ADR 0017](docs/adr/0017-scope-of-version-1.md). Requirements: [REQUIREMENTS.md](REQUIREMENTS.md).

## State

| Milestone | State |
| --- | --- |
| M0: Repository bootstrap | Done, except that the repository is still private |
| M1: Walking skeleton with notifications | Done |
| M2: Discovery and collection for SATA and NVMe | Done |
| M3: Evaluation and configuration | Done |
| M4: State and notification policy | Done |
| M5: Packaging, timer and installation | Built, waits for the remaining checks on a real Proxmox VE host and the acceptance on the test cluster |
| M6: SAS and hardware RAID on recorded data | Built, all six slices merged; results 2 and 3 on a cluster node are open |
| M7: Hardening, documentation, release 1.0 | Started; the hostile-string tests, the traceability table and the user documentation are merged, the rest is open; see its section |

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

Additionally, since 2026-10-08, a standalone Proxmox VE 9.2.3 host `pve1` that is not part of the cluster and may be changed freely: one Intenso SATA SSD, one USB device (virtual drive of a KVM-over-IP device), no NVMe drive ([Research 07](docs/research/07-standalone-host-pve1.md)). It is used for tests that change the notification matchers or break the bridge. It does not replace the cluster for the acceptance steps.
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
2. The wear value shown for each SSD equals the "Wearout" column of the web interface, or `scan` names the vendor-neutral source that gives a different value ([ADR 0021](docs/adr/0021-wear-value-source.md)). On the test cluster this applies to the Fanxiang S301 on `pve5`: 44 % from `endurance_used` against 0 % in the web interface.
3. `pve-smart-alert dump-fixture --all` writes an archive that contains no real serial number.
4. With a drive name that does not exist as a manual entry, the scan still completes and reports that device as unreadable.
5. With the default matcher restricted so that it no longer matches the type `pve-smart-alert`, `pve-smart-alert doctor` reports `routing` as `warn`, names the severities that are not routed and says how to add a matcher. `pve-smart-alert test-notification` says that no matcher matched. With the matcher of M1 in place, which routes only `warning` and `error`, `doctor` reports `routing` as `warn` and names `info` and `notice`. With that matcher extended to `info,notice,warning,error`, both report the matching matcher and `doctor` reports `ok`. A severity of the tool that no matcher routes always means `warn`; this is how the rules for `ok` and `warn` in [ADR 0020](docs/adr/0020-routing-check.md) are read.

How to run it: install the new package on each node, run [`scripts/collect-node-data.sh`](scripts/collect-node-data.sh), which also records the output of `scan` and `doctor`, and check the steps against the archive. Steps 3, 4 and 5 and the test notification need the commands given there in addition. Since 2026-10-05 the matcher of the tool on the test cluster routes all four severities; for the `warn` case of step 5 it is set back to `warning,error` for the test.

Open questions this milestone answers: Q-S1 to Q-S4 and Q-N8.

State: done. The acceptance run of steps 1 to 4 passed on all three nodes of the test cluster on 2026-10-12, with the package 0.2.0 ([Research 06](docs/research/06-test-cluster-recordings.md)): every drive appeared exactly once with the right identity and volume group; every wear value equaled the web interface except on the Fanxiang S301 on `pve5`, where `scan` names both values; the fixture archives of all three nodes contain no real serial number or WWN, checked against the raw recordings; and a manual entry for the nonexistent device `/dev/sdz` was reported as unreadable while the scan completed. Step 5 had already passed on `pve7` on 2026-10-07 ([ARCHITECTURE.md](ARCHITECTURE.md) section 10), and `doctor` reported the `fallback` line as `ok` on all three nodes in this run. Steps 1, 3 and 4 and the three cases of step 5 had also run on the standalone host `pve1` on 2026-10-08, together with the bridge made unusable ([Research 07](docs/research/07-standalone-host-pve1.md)).

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

State: done. The acceptance passed on the standalone host `pve1` and on all three nodes of the test cluster on 2026-10-12, with the package 0.3.0 after three fixes from the run on `pve1`.

- Done: the catalog of `checks.py` with the evaluation of one snapshot, the severities and the model of ADR 0010; the configuration sections `[checks."<id>"]` and `[[drive]]` with strict validation, the normalization of overrides that repeat the default, and the last-good fallback of FR-406 as `last-good-config.json` in the state directory; the commands `check --dry-run`, `config check` and `config show` with the origin of each value; the per-drive `exclude` and `detail` of FR-403 in discovery; the decoding of attribute 188 (Q-T1); the derived fixture `failing-hdd` ([tests/fixtures/SOURCES.md](tests/fixtures/SOURCES.md)), which fails several checks at once; and the review of the provisional thresholds against the recordings of all three nodes: the healthy drives stay below every threshold, as a test shows. The events and the missing and unreadable drive checks wait for the state of M4, and Q-T2 to Q-T4 keep their recorded answers until feedback from the fleet arrives.
- Acceptance on `pve1` (one Intenso SATA SSD, no NVMe drive, smartmontools 7.5, Proxmox VE 9.2.3): `check --dry-run` on the real drive lists no findings for the healthy drive and sends nothing; with the fake smartctl replaying `failing-hdd`, the dry run shows all 11 expected findings with the expected severities, and the event `ata.crc_errors` stays silent without a baseline; `config check` accepts a valid file and the absence of the file, and an invalid file names key and line for an unknown key, a wrong type, an out-of-range threshold, an unknown key in a check and a `[[drive]]` entry with two selectors, each time with exit status 1; `config show` prints every key with its effective value and origin; a global threshold override produces its finding, a per-drive disable removes it for that drive only, a per-drive `exclude` removes the drive from monitoring with the reason "excluded", a per-drive `detail = "basic"` changes what is read, and the first of two matching `[[drive]]` rules wins in every case (FR-403); an invalid file at run time continues with `last-good-config.json` or, without one, with the built-in defaults, with the error on standard error, and `doctor` warns and exits 0 (FR-406). The wear of the SSD is 3 % from `endurance_used`, the web interface shows "Wearout" 100 from the same attribute 177 that the tool keeps as the vendor-attribute value; attribute 188 is not reported by this drive, so it could not be compared with the web interface, and the decoding of its packed value is covered by the `failing-hdd` fixture (600 from "600 (0/600/0)").
- The run on `pve1` found three failures, each fixed with a regression test: an unknown check identifier named no line; the wear of an ATA drive read with `detail = "basic"` showed the attribute guess of smartmontools as the vendor-neutral source (0 % instead of 3 %, [Research 03](docs/research/03-smart-indicators.md)); and a run without a last good configuration claimed to use one instead of the built-in defaults.
- Acceptance on the cluster, steps 1 to 4 on `pve5`, `pve6` and `pve7` (run by the maintainer on 2026-10-12, with the package 0.3.0 that contains the fixes, read from the logs of the three nodes): `check --dry-run` on the real drives exits 0 with no findings on every node, 1 drive on `pve5`, 2 on `pve6` and 3 on `pve7`, so the evaluation of NVMe drives is confirmed on real hardware; with the fake smartctl replaying `failing-hdd`, the dry run shows the 11 expected findings (7 critical, 4 warning) and the event `ata.crc_errors` stays silent; a raised threshold of `ata.reallocated_sectors` removed that finding (10 findings); a per-drive override removed the `ata.pending_sectors` finding for the drive selected by `model = "Samsung*"`, so the model pattern works; the typing error "notise" made `config check` name the key, the allowed keys and line 4 with exit status 1, while the dry run continued with the last good configuration — the one of the per-drive step, so the pending-sectors finding was absent there, which is what FR-406 demands — and `doctor` warned with exit status 0; `config show` printed every key with its origin. The drives of the cluster are healthy, so no finding was raised on real hardware; the failing drive is covered by the fixture. The logs and fixture archives of the run stay on the nodes, where the acceptance scripts wrote them: they contain real serial numbers and WWNs and do not belong into the repository.

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

State: done. The acceptance passed on the standalone host `pve1` on 2026-10-12, with the package 0.4.0 and the fake smartctl, after all ten steps had passed as scenario tests. The work is on the branch `feature/m4-state`.

- Done: the state store of `state.py` with atomic replacement, the setting aside of a corrupt file or one of a newer schema, the migration mechanism and the clamping of future timestamps ([ARCHITECTURE.md](ARCHITECTURE.md) section 9).
- Done: the scenario test frame: the scenarios of `tests/scenarios.py`, whose steps the fake smartctl replays and which can be written out for a real host, and a clock, a state directory and a recording transport in `tests/unit/frame.py`.
- Done: the configuration keys of the notification policy in `[notify]` and `[notify.reminder]`, and the confirmation count `confirm_runs` of a condition check, with the defaults of ADR 0009 (FR-404); `config show` lists them.
- Done: the notification planner of `planner.py` with every rule of ADR 0009 as a pure function of state, observation, configuration and time, each rule with a test that drives it run by run with an injected clock.
- Done: the event checks against the baselines of the state, the checks `drive.missing` and `drive.unreadable` in the catalog, and the detection of the tool conditions in `tool_conditions.py`.
- Done: the renderer of `render.py` with the layout of ARCHITECTURE.md section 10 for a message about one drive, the summary, the first-run summary and a message about the tool, each compared with a golden file.
- Done: the commands `pve-smart-alert check`, which runs the sequence of ARCHITECTURE.md section 3 in `run.py` and delivers through the transports, the dry run that prints the planned notifications, and `pve-smart-alert status`; the line `state` of `doctor`; and the ten acceptance steps below as scenario tests with an injected clock (`tests/unit/test_acceptance_m4.py`).
- Acceptance on `pve1` (Proxmox VE 9.2.3, smartmontools 7.5, default matcher to `mail-to-root`), with the steps written by `python3 tests/scenarios.py build` on the host and `pve-smart-alert status` after every run: (1) the first run sent one summary that lists the drive, severity info; (2) the second run sent nothing; (3) "3 pending sectors" sent one warning that names `/dev/sda`, the model, the serial number, 3 pending sectors and the thresholds; (4) the same step again sent nothing; (5) "20 pending sectors" sent one critical notification, severity `error`, escalated from warning; (6) "healthy again" sent nothing in its first run and one recovery with severity info in its second; (7) "drive gone" sent nothing in its first run, one notification about the missing drive in its second, and nothing in a third; (8) with five drives too hot, the first hot run sent nothing while the temperature waited for its confirmation, the second sent one summary of the five drives, and a third sent nothing; (9) `status` showed the active condition, the waiting temperatures and the missing drive at each step; (10) after the state file was deleted, the next run sent one first-run summary with the existing finding. Every run exited 0, and the journal shows `notified via target mail-to-root` for each of the eight notifications. Afterwards `check` against the real smartctl sent one first-run summary and, in a second run, nothing, and `doctor` reported the lines `smartctl`, `bridge` and `state` as `ok`. The host was then set back to the package 0.3.0 with its configuration and last good configuration unchanged, checked by checksum, and without a state file. The logs stay outside the repository.
- The cluster name of a notification is read from `/etc/pve/corosync.conf`, which the standalone `pve1` does not have. On the test cluster the maintainer checked on `pve5` on 2026-10-12 that the file names the cluster with `cluster_name` in its `totem` section (Q-N9, answered).

## M5: Packaging, timer and installation (M)

Goal: one command, then no care.

Deliverables:

- Complete Debian package with units, failure reporter, reference configuration and maintainer scripts. The service accepts exit status 3 of `pve-smart-alert check`, a run skipped because another one holds the lock, as success (`SuccessExitStatus=3`) ([ADR 0013](docs/adr/0013-packaging-and-installation.md), [ADR 0006](docs/adr/0006-scheduling.md)). The manual page is part of the package since the user documentation of M7.
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

State: the development of M5 is on `main` since pull request #4, which merged the host-tested work of `feature/m5-packaging` onto the units of pull request #3; CI is green there. What is left needs a real Proxmox VE host (checklist below), and 0.5.0 is tagged only after it passed. Builds for test hosts are pre-releases `0.5.0~devN` until then, so that each one installs as an upgrade ([ADR 0027](docs/adr/0027-pre-release-versions-for-test-builds.md)).

- Done: the three units of ADR 0006 in `systemd/` and the failure reporter `libexec/report-failure` in the package ([ARCHITECTURE.md](ARCHITECTURE.md) section 13); maintainer script snippets for the timer only, read from the source of debhelper 13.24.2; purge removes `/run/pve-smart-alert/` as well.
- Done: the sandboxing of the check service, [ADR 0025](docs/adr/0025-sandboxing-of-the-check-service.md) (Q-P1).
- Done: the lines `timer`, `pve` and `smartd` of `doctor`; with the line `controllers` of M6, slice 4, `doctor` covers all of FR-603.
- Done: `scripts/install.sh`; the package test of ADR 0016 in a clean container in CI (`scripts/package-test.sh`), which passed on 2026-10-15 (Q-P3); the release workflow `.github/workflows/release.yml`.
- Done on `pve1` with test builds of 0.5.0 from `feature/m5-packaging` (2026-10-13): the installation starts the timer and the first check at once, which sent the first-run summary; an upgrade restarts the timer without a run, keeps the state and sends no summary (Q-P2); a run made to fail on purpose with a drop-in sent one failure mail, which reached `proxmox-mail-forward`, and a second failure on the same day sent none; a run skipped because of the lock exited 3 and counted as success; `systemd-analyze verify` accepts the units; an unreachable SMTP target blocks the bridge for about 5 seconds and a webhook target for about 10 (Q-N4). The sandboxing options of ADR 0025 were tested with both transports and a check (Q-P1).
- The tests on `pve1` found that a run logged one progress line per drive to the journal besides its summary line (FR-606); the progress now goes to a terminal only.
- Done on `pve1` (2026-10-16): the upgrades from 0.4.0 to 0.5.0~dev1, from 0.5.0~dev1 to 0.5.0~dev2 and from 0.5.0~dev2 to 0.5.0~dev3, installed with `apt` as a user would, kept the configuration, the last good configuration and the state file byte for byte, and the timer active and enabled ([ADR 0027](docs/adr/0027-pre-release-versions-for-test-builds.md)).
- Done on `pve1` (2026-10-18), with the build `0.5.0~dev4`:
  - The upgrade from `0.5.0~dev3` kept `config.toml`, `last-good-config.json` and `state.json` byte for byte (SHA-256 before and after), and the timer active and enabled.
  - A run made to fail on purpose with a drop-in started the failure reporter, which handed one mail to `proxmox-mail-forward`; a second failure on the same day sent none ("already reported"). That the mail arrived, and its text, are not confirmed by the maintainer yet.
  - After a reboot the timer ran by itself, the stamp of the failure reporter was gone, and the first run was `run ok`.
  - Installation (steps 1 to 3): `scripts/install.sh`, with the package served from `127.0.0.1`, installed the build after the checksum matched and created the link of the timer. The first run came at once and sent the first-run summary through the target `mail-to-root` (one drive, no findings). The timer is active with the next run about 30 minutes later, the journal has one summary line per run, and `doctor` reports every line as `ok`.
  - Purge (step 7): the first purge left `__pycache__` directories with byte code of `__init__`, `model` and `parsers` below `/usr/share/pve-smart-alert/pve_smart_alert/`, and dpkg warned that the directory was not empty. The launcher writes no byte code, so the files came from something else, and where they came from is still unknown. After they were removed by hand and the package was installed again with `scripts/install.sh`, the second purge left no file, link, directory, unit or dpkg entry, with no warning. A control test found no `__pycache__` after an installation, a `doctor` run as root and a normal service run. The purge now removes the directory of the tool ([ADR 0035](docs/adr/0035-purge-removes-the-package-directory.md)); that this suffices, without removing anything by hand, is still to be checked on the host.
  - With `pve-cluster` stopped (a standalone host, so not a node that lost quorum), `check` and `doctor` completed with status 0, and `routing` and `fallback` were `skip`. `test-notification` was handed over as mail, with the reason for the fallback in its answer, but `proxmox-mail-forward` could not route it: without pmxcfs it finds no address for `root@pam`, so the fallback does not reach a person while pmxcfs is down (Q-N5). Stopping `pve-cluster` also removed the SSH key of root, which Proxmox VE links to `/etc/pve/priv/authorized_keys`, and locked the session out until the service was started again.
- Done on `pve1` (2026-10-30), with the build `0.5.0~dev5`: the upgrade from `0.5.0~dev4` kept `config.toml`, `last-good-config.json` and `state.json` byte for byte (SHA-256 before and after), left the timer active and enabled, and installed the manual page, which no earlier package carried. `doctor` reported every line as `ok` and `check --dry-run` found nothing on the one drive and sent nothing.
- Done on `pve1` (2026-10-30), with the build `0.5.0~dev5`:
  - The failure reporter of `main` was tried with a run made to fail on purpose. It sent one mail with the subject `PVE SMART Alert: a run failed on pve1.local`, the unit, the result and the last lines of the run (`deliberate-failure-line-of-the-test`); a second failure on the same day logged `a failure was already reported today, no mail sent` and sent nothing. Both mails were handed to the notification system as the target `mail-to-root` and wait in the queue of postfix for `postmaster@miloo.at`, because the relay is unreachable from the test host; that they arrive in an inbox is not confirmed here. The drop-in that made the runs fail was removed, and a normal run followed as `run ok`.
  - Purge (step 7), with a `__pycache__` planted below `/usr/share/pve-smart-alert/pve_smart_alert/` before it, as something outside the package would leave it: the purge of [ADR 0035](docs/adr/0035-purge-removes-the-package-directory.md) left no file, link or directory of the tool (checked for `/etc/pve-smart-alert`, `/var/lib/pve-smart-alert`, `/run/pve-smart-alert`, `/usr/share/pve-smart-alert`, `/usr/libexec/pve-smart-alert`, the manual page, the templates and the three units, and the timer link), and dpkg no longer knew the package. A reinstall of `0.5.0~dev5` restored the configuration with the same SHA-256 as before, the timer and the manual page; the next run sent one summary and created the state file.
- Found in the same run and fixed before `0.5.0~dev5`, each with a test: `doctor` ended in a traceback when it was interrupted with Ctrl+C inside `pvesh`, and any command now ends with the line `pve-smart-alert: interrupted` and exit status 130; `scripts/install.sh` announced an installation and a first check that would not come when apt installed nothing, and it now reads the state and the version from dpkg before and after, names an upgrade separately, and stops with a line when apt fails; and the purge left the `__pycache__` above, and it now removes the directory of the tool. The package test plants such byte code before the purge and fails if the directory stays, so the regression runs in CI and not only on a host.
- Noted while fixing the interruption above, and not fixed: a command interrupted with Ctrl+C ends with 130, but the program it was waiting for is left running. Every program the tool starts runs in its own session ([`process.py`](src/pve_smart_alert/process.py)), so the Ctrl+C of the terminal does not reach it; the runner kills a program when its wait times out, and an interrupt unwinds that wait, so once the command has ended nothing stops the program. A notification that the bridge was still sending can arrive after the run ended and be planned again by the next run. The traceback that the interrupt ended with before made no difference to this.

Verified only by static checks, without systemd running the units:

- The values of the units, the sandboxing of ADR 0025, the absence of an `[Install]` section in the services, and the install paths: unit tests (`tests/unit/test_units.py`).
- What systemd makes of the units: `systemd-analyze verify` in the package job of CI.
- The maintainer scripts handle the timer and no service: a check of the generated snippets in the package job of CI.
- The failure reporter: integration tests with a stand-in mail command and journal (`tests/integration/test_report_failure.py`). The reporter on `main` replaced the one tested on `pve1`; it reads the journal of the failed run through `MONITOR_INVOCATION_ID`.

### Still needs a real Proxmox VE host

- [x] The failure reporter of `main` with real mail: a run made to fail on purpose sends one mail with the lines of that run, a second failure on the same day none (2026-10-30; the mail waits at the relay of the test host, so its arrival in an inbox is still open).
- [x] Reboot: runs resume by themselves, and the stamp of the failure reporter is gone (2026-10-18).
- [x] Purge on `pve1`: nothing of the tool is left (2026-10-30, with byte code that no package owned planted before the purge; the `postrm` of [ADR 0035](docs/adr/0035-purge-removes-the-package-directory.md) removed it without help).
- [ ] Quorum loss: a node without quorum still runs its check and sends through the fallback if needed (Q-N5). The half "pmxcfs not running" was tried on `pve1`, with the result above; the half "no quorum" needs a cluster.
- [ ] Acceptance steps 1 to 8 above on `pve1`, then on the cluster nodes `pve5`, `pve6` and `pve7`. Steps 1 to 3 and 7 passed on `pve1` on 2026-10-18; steps 4, 5 and 6 were observed there and wait for the maintainer to tick them; step 8 needs a node that lost quorum.

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

Open questions this milestone answers or narrows: Q-R1 to Q-R7 and Q-R9 to Q-R11.

State: built; the runs of results 2 and 3 on a cluster node are open. The work was split into six slices, one branch `feature/m6-<slice>` each, built one after the other and merged into `main` by pull request:

1. `recordings`: the public recordings of [Research 08](docs/research/08-public-recordings.md) as fixtures, and the anonymization of SCSI names and the import of other projects' test data ([ADR 0026](docs/adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)).
2. `scsi`: the parser for SCSI and SAS drives and the checks `scsi.*` of the catalog. Thresholds that rest only on recordings are listed in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) for the review in M7.
3. `megaraid`: pass-through types, logical volumes and enclosures skipped with a reason (this includes the Intel RAID volume of Research 08, which slice 2 counted as monitored), de-duplication in JBOD mode, changing device IDs, and notifications that name controller and device ID. A logical volume is recognized by structured fields first and by the message of smartctl only as a second signal.
4. `unsupported-controllers`: controllers whose drives cannot be queried, such as `mpi3mr`, in `scan`, `doctor` and `tool.unsupported_controller`. `mpt2sas` and `mpt3sas` are HBAs whose drives smartctl reads directly and are never reported as unsupported; `ahciem`, seen next to the `ahci` hosts on the TrueNAS SCALE kernel and taken for its AHCI enclosure management (where it comes from was not checked in kernel source), is no drive controller and produces no warning or finding (decided by the maintainer on 2026-10-16, after `mpt2sas` and `ahciem` were seen on the TrueNAS host).
5. `hpe-probe`: the experimental `cciss,N` probe with its configuration key, on synthetic fixtures only.
6. `support-table`: scenarios per controller family, the hardware support table with evidence labels, manual entries for the other pass-through types, and the call for recordings.

Decided for M6 (2026-10-16): the non-medium error count of SCSI drives is not checked, because smartctl writes it only as text (Research 08); the recordings of HPE controllers that were found are evidence only, so HPE Smart Array is built on synthetic fixtures and labeled "Experimental".

- Done: slice 1, merged in pull request #6: 13 public recordings as fixtures, ADR 0026, Research 08.
- Done: slice 2, merged in pull request #7: the SCSI parser and the checks `scsi.*`, `health.failed` with the exception of a SAS drive, and a recording of the maintainer's TrueNAS host with SAS SSDs behind an LSI SAS2308 HBA, which answered Q-R6. Pull request #9 recorded that host again with the call of the tool.
- Done: slice 3, merged in pull request #10: the pass-through types, the location of a drive behind the controller, logical volumes and enclosures skipped by [ADR 0028](docs/adr/0028-logical-volumes-and-enclosures.md), and the scenarios `megaraid-jbod`, `megaraid-id-change` and `megaraid-degraded`, which show result 2 above on derived data. MegaRAID rests on public recordings of SATA drives and scans and on derived data; SAS behind MegaRAID is derived only.
- Done: the test frame refuses every program of the host (`tests/guard.py`, pull request #11); one test had reached the smartctl of the machine it ran on.
- Done, merged in pull request #13: the notification field `device-id` of [ADR 0029](docs/adr/0029-notification-field-device-id.md), decided by the maintainer on 2026-10-16 (Q-N10). It carries the device ID of a drive read through `megaraid,N` or `sat+megaraid,N` and is absent for every other drive; `device` stays as it is (NFR-21). `cciss,N` gets it with slice 5.
- Done: a state that 0.5.0~dev2 wrote is read and continued by the current code (`tests/fixtures/state/`, pull request #14); the state format has not changed since schema 1.
- Done, merged in pull request #15: slice 4, controllers whose drives cannot be queried, by [ADR 0030](docs/adr/0030-controllers-whose-drives-cannot-be-queried.md). The drivers of the SCSI hosts are read from sysfs; `mpi3mr` is reported in `scan`, in the line `controllers` of `doctor` and as `tool.unsupported_controller`, which clears with a recovery and is frozen while sysfs cannot be read; `mpt2sas`, `mpt3sas`, `ahciem` and unknown drivers are not. The SCSI hosts of the TrueNAS host, the cluster nodes and `pve-test`, recorded on 2026-10-16, report nothing ([Research 08](docs/research/08-public-recordings.md)); `mpi3mr` rests on synthetic trees only, and whether one in HBA personality should be reported is Q-R7.
- Done, merged in pull request #17: a small pull request that makes the notification of `tool.unsupported_controller` more helpful, by [ADR 0031](docs/adr/0031-switching-tool-conditions-off.md): the notice names how many drives the run monitors on the host (`no drive`, `1 drive`, `N drives`), left out when the run could not count them, and it says how it is switched off for a controller in HBA mode whose drives all appear in `scan`. The configuration can switch every condition of the tool off with `[checks."<id>"] enabled = false`, like a check of a drive (FR-408), which `config show` and the reference document; the text of a condition of the tool is cut at 1000 characters instead of 200, because the message used to say less than the condition. Q-R7 stays open.
- Done, merged in pull request #18: slice 5, by [ADR 0032](docs/adr/0032-hpe-smart-array-probe.md): the experimental probe for the drives behind an HPE Smart Array controller. It reads `cciss,0` upwards on the lowest `/dev/sgN` of a controller whose SCSI host has the driver `hpsa`, stops after 3 device IDs in a row that answer nothing and never above 127, because `N` is a position in the device list of the controller (Research 08, addition of 2026-10-17). A `smartpqi` host is named in `scan` and `doctor` and not probed; every `cciss` form is read with `--nocheck=standby`, so a drive in standby is not woken (FR-203); `[discovery] probe_cciss` switches the probe off, and it is on by default, and the drives that only the probe can find are then forgotten silently instead of being reported as missing. A probed drive has the location `/dev/sg1 (hpsa), device 0` and the field `device-id`, which finishes [ADR 0029](docs/adr/0029-notification-field-device-id.md) for `cciss,N`. There is no recording of an HPE host: the tests derive two drives from the TrueNAS recording and model an empty bay on the source, and Q-R2 is narrowed.
- Done, merged in pull request #20: slice 6. Scenarios named after the controller families: `onboard-sata-nvme`, `hba-sas`, the three MegaRAID scenarios, `hpe-smart-array`, `unsupported-mpi3mr` and `manual-pass-through`; a scenario can name the SCSI hosts, SCSI generic nodes and manual entries of its host, and `scenarios.py build` says what a real host needs besides the steps. The hardware support table with the evidence labels of ADR 0016 and the call for recordings are in [docs/hardware-support.md](docs/hardware-support.md), and a test keeps the table and the scenarios in line (NFR-16). The scenarios and two rounds of review found these faults, fixed by [ADR 0034](docs/adr/0034-manual-entries-of-other-pass-through-types.md) and in the pull request: a drive read through `aacraid` or `hpt` on a block device took the location, pool and inquiry data of that logical volume, and could be skipped as one, also with `sat` and its options before the type; a drive behind 3ware, Areca, Adaptec, HighPoint or SSSRAID was read without the standby check; a SAS drive in standby, such as one behind cciss, counted as unreadable, because smartctl names its power condition in words; the JMicron types, which smartctl reads by writing to the drive, were accepted, also from a last good configuration; `dump-fixture` named the type of the output instead of the call, so a recording of these controllers did not replay; and the command of `smart.disabled` for a drive behind a controller lacked its type. These types get no `device-id` in version 1 (Q-R11). The source of smartmontools shows that the scan lists the drives of an SSSRAID controller ([Research 04](docs/research/04-hardware-raid.md), addition of 2026-10-17). The TrueNAS recording of 2026-10-16 was replayed through `scan`, `check --dry-run` and the renderer after the last code change of the pull request and shows four monitored drives without findings, as in Research 08; the host was not recorded again for this slice.
- Open: `dump-fixture --all` records the drives of the scan and the manual entries, not the drives only the HPE probe finds, and not the drivers of the SCSI hosts; the call for recordings asks for both by hand.

Results you can test, as built:

1. Partly done: for the families that recordings, derived or synthetic data can show, `make test` runs a scenario named after each and passes. Seven rows of the support table have none, because no replayable data of them exists, the tool never reads them, or a test of discovery covers them instead: SATA drives behind an HBA, SAS drives behind `mpt3sas`, the Intel RST volume (a test of discovery replays it), `smartpqi`, the old `cciss` driver, the JMicron types and drives behind USB bridges.
2. Built on derived data: the scenarios `megaraid-jbod` and `megaraid-degraded` show it in the test frame. The run on a cluster node with the fake smartctl waits for the maintainer. On a cluster node the location shows the node without the driver `megaraid_sas`, because no node has such a SCSI host; `scenarios.py build` says so.
3. Built on recorded data: the scenario `hba-sas` replays the TrueNAS recording with a derived finding; the derived SAS drive behind MegaRAID is in `megaraid-degraded`. The run on a cluster node waits for the maintainer.
4. Done: [docs/hardware-support.md](docs/hardware-support.md) states for every family how it was verified.

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

State: started on 2026-10-17. Three parts are merged, in pull requests #21, #22 and #23; the rest is open and listed below.

- Done, merged in pull request #21: hostile strings in drive data. `tests/unit/test_hostile_strings.py` feeds a model, serial number and firmware with C0 and C1 controls, an ANSI escape, newlines, a TAB, a right-to-left override, a lone surrogate, a very long value and Handlebars and shell syntax, a pool label and the inquiry data of a logical volume with escapes, and a device name of the scan that fails its check, through `scan`, `status`, `check --dry-run`, the notifications, their fields and data, a mail, the journal lines, the progress line and the state file, and the answer of a transport through `test-notification` and the journal lines; the bridge gets a separate string with Handlebars and shell syntax.
- Still open for the security review: the other points of [ARCHITECTURE.md](ARCHITECTURE.md) section 14; how the notification system renders the data of a message (Q-N11); a cut value carries no mark; a model or serial number of control characters only is left out of the fields; a selector copied from `scan` misses a drive whose model holds a removed character, because the identity keeps it (ADR 0005).
- Done, merged in pull request #22: [docs/traceability.md](docs/traceability.md), a dated snapshot that relates every requirement to its tests and acceptance steps and lists the requirements that no test covers and those whose acceptance step ROADMAP does not have.
- Still open for result 2: a test for NFR-07, and a step for NFR-07 and NFR-09, which the two lists of the table name; the acceptance steps that the table names and that are not ticked here; how a requirement verified by inspection alone, such as NFR-19, counts for result 2; and a check of the table row by row when it is made again for the release.
- Done, merged in pull request #23: [docs/troubleshooting.md](docs/troubleshooting.md) and the source of the manual page, `man/pve-smart-alert.8`, which the package installs since the fix of `0.5.0~dev5`; with them the package installs the reference configuration uncompressed, at the path the tool names.
- Still open for the user documentation: whether installation and the configuration reference stay in the README and in `config/config.reference.toml` or get documents of their own; the notice `tool.unsupported_controller` names its table and key on one line, which is not valid TOML, in the wording that [ADR 0031](docs/adr/0031-switching-tool-conditions-off.md) prescribes; while the file is invalid, `config show` shows the values of the last good configuration with origins taken from the invalid file.

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
