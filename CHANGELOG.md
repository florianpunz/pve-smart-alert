# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository bootstrap: license, contribution guide, security policy, development tooling, continuous integration and a package skeleton with the `pve-smart-alert --version` command.
- `pve-smart-alert test-notification` sends one test notification with a selectable severity and reports what the notification system did with it (FR-520).
- Notifications reach the Proxmox VE notification system through a Perl bridge that calls `PVE::Notify`, with mail to root as the automatic fallback when that route fails ([ADR 0008](docs/adr/0008-notification-integration.md)).
- The two pass-through templates of the tool are installed into the template directory of the notification system.
- `pve-smart-alert doctor` reports the state of the configuration, the notify bridge, the notification templates and the mail command (FR-603).
- `scripts/collect-node-data.sh` collects the drive, storage and notification data of one node into one archive, for development and acceptance runs.
- A Debian package with a launcher, the bridge, the templates and the configuration file; `make build` builds it together with the Python distribution ([ADR 0013](docs/adr/0013-packaging-and-installation.md)).
- `pve-smart-alert doctor` reports the routing of the notifications: it reads the matchers and targets through `pvesh` and warns when a severity of the tool reaches no target, because the notification system drops such a notification without an error ([ADR 0020](docs/adr/0020-routing-check.md)).
- `pve-smart-alert test-notification` names the matchers that route the test notification, or says that none does.
- The configuration accepts `[smartctl]` with `path`, `timeout` and `detail`, and manual devices in `[[discovery.device]]` (FR-104); the reference configuration documents them.
- The collector runs smartctl for one drive with a timeout, leaves a drive in standby asleep, and tells usable data from an unreadable drive by the exit status and the JSON ([ADR 0004](docs/adr/0004-smartctl-json-as-data-source.md)).
- Discovery finds the drives of a host from the device scan of smartctl and the manual devices, reads each once, adds transport, links and the volume group, pool or array from lsblk, skips remote devices, devices that are not disks, drives without SMART and drives an exclude rule selects, and keeps a drive reached through several paths once ([ADR 0005](docs/adr/0005-drive-discovery-and-identity.md)).
- The configuration accepts exclude rules in `[discovery]`, which select drives by model pattern, serial number or WWN ([ADR 0024](docs/adr/0024-drive-selectors.md)).
- The wear value of an SSD comes from `endurance_used`, the device statistics or the NVMe health log, and only then from the vendor attribute of the web interface, with its source, and the value the web interface shows is kept next to it ([ADR 0021](docs/adr/0021-wear-value-source.md)).
- Parsers for ATA and NVMe turn the JSON of smartctl into snapshots of the drive model; values a drive does not report are left out instead of guessed (FR-206).
- `tests/fake-smartctl` replays recordings for the tests, including drives that sleep, hang or cannot be opened ([ADR 0016](docs/adr/0016-test-strategy.md)).
- `scripts/make_fixtures.py` turns an archive of the collection script into anonymized fixtures ([ADR 0023](docs/adr/0023-anonymization-of-recordings.md)).
- `pve-smart-alert doctor` reports the route of the fallback in a line `fallback`: whether a matcher routes mail to root, which arrives as `system-mail`, and whether `/root/.forward` hands it to the notification system ([ADR 0022](docs/adr/0022-fallback-routing-check.md)).

### Changed

- `pve-smart-alert test-notification` points out that an empty log can mean that no matcher matched.
- The wear value of an SSD is taken from the vendor-neutral sources first and from the vendor attribute of the Proxmox VE web interface last, and the source is shown ([ADR 0021](docs/adr/0021-wear-value-source.md)).
- The example matcher in the README routes all four severities of the tool.
- With `transport = mail`, the line `routing` of `pve-smart-alert doctor` checks the route of mail to root instead of being skipped, and `pve-smart-alert test-notification` follows a test that went as mail.
- `pve-smart-alert test-notification` mentions that an empty log can mean that no matcher matched only when the line `Matchers` cannot decide it, and no longer after a test that went as mail.
- When a matcher would route a notification but it or its targets are disabled, `pve-smart-alert doctor` and `pve-smart-alert test-notification` name it instead of advising a new matcher.

[Unreleased]: https://github.com/florianpunz/pve-smart-alert/commits/main
