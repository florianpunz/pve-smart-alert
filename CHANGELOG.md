# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `pve-smart-alert --version` prints the version of the tool.
- `pve-smart-alert test-notification` sends one test notification with a selectable severity and reports what the notification system did with it (FR-520).
- Notifications reach the Proxmox VE notification system through a Perl bridge that calls `PVE::Notify`, with mail to root as the automatic fallback when that route fails ([ADR 0008](docs/adr/0008-notification-integration.md)).
- The two pass-through templates of the tool are installed into the template directory of the notification system.
- `pve-smart-alert doctor` reports the state of the configuration, the notify bridge, the notification templates and the mail command (FR-603).
- A Debian package with a launcher, the bridge, the templates and the configuration file; `make build` builds it together with the Python distribution ([ADR 0013](docs/adr/0013-packaging-and-installation.md)).
- `pve-smart-alert doctor` reports the routing of the notifications: it reads the matchers and targets through `pvesh` and warns when a severity of the tool reaches no target, because the notification system drops such a notification without an error ([ADR 0020](docs/adr/0020-routing-check.md)). With `transport = mail`, the line `routing` checks the route of mail to root, which every notification takes then.
- `pve-smart-alert test-notification` names the matchers that route the test notification, or says that none does; a test that went as mail is followed as the notification that mail to root becomes. When the notification system logged nothing, it points out that an empty log can mean that no matcher matched.
- The configuration accepts `[smartctl]` with `path`, `timeout` and `detail`, and manual devices in `[[discovery.device]]` (FR-104); the reference configuration documents them.
- `pve-smart-alert scan` shows every device found with its source and what became of it, and for each drive its model, serial number, class, what uses it, its wear value with the source and, where it differs, the value of the web interface (FR-108).
- `pve-smart-alert dump-fixture` records the device scan, lsblk and the output of smartctl for all or selected drives as one archive, with serial numbers, WWNs and UUIDs replaced by placeholders, and writes nothing when a real value would be left (FR-604, [ADR 0023](docs/adr/0023-anonymization-of-recordings.md)).
- `pve-smart-alert doctor` reports smartctl with its version and fails for a smartctl older than 7.0.
- Discovery finds the drives of a host from the device scan of smartctl and the manual devices, reads each once, adds transport, links and the volume group, pool or array from lsblk, skips remote devices, devices that are not disks, drives without SMART and drives an exclude rule selects, and keeps a drive reached through several paths once ([ADR 0005](docs/adr/0005-drive-discovery-and-identity.md)).
- The configuration accepts exclude rules in `[discovery]`, which select drives by model pattern, serial number or WWN ([ADR 0024](docs/adr/0024-drive-selectors.md)).
- The wear value of an SSD comes from `endurance_used`, the device statistics or the NVMe health log, and only then from the vendor attribute of the web interface, with its source, and the value the web interface shows is kept next to it ([ADR 0021](docs/adr/0021-wear-value-source.md)).
- `pve-smart-alert doctor` reports the route of the fallback in a line `fallback`: whether a matcher routes mail to root, which arrives as `system-mail`, and whether `/root/.forward` hands it to the notification system ([ADR 0022](docs/adr/0022-fallback-routing-check.md)).
- When a matcher would route a notification but it or its targets are disabled, `pve-smart-alert doctor` and `pve-smart-alert test-notification` name it instead of advising a new matcher.
- `pve-smart-alert check --dry-run` evaluates every drive against the checks of the [check catalog](docs/check-catalog.md) and prints the findings with their check, severity, value and threshold; it sends nothing and changes no state (FR-601). The run that plans and sends notifications arrives with the next milestone.
- The evaluation: a catalog of independent checks with stable identifiers, the drive's own failure verdict always critical, raw defect counters with thresholds from published failure rates, wear capped at warning, and missing data never a finding ([ADR 0010](docs/adr/0010-health-evaluation-and-default-thresholds.md)). The command timeouts of attribute 188 are read decoded where the drive packs them (Q-T1).
- The configuration accepts the global overrides of `[checks."<check-id>"]`: `enabled` and the thresholds `notice`, `warning` and `critical`, one number or, for the temperature, a table of the drive classes (FR-402).
- The configuration accepts per-drive overrides in `[[drive]]`, selected by model pattern, serial number or WWN: `exclude` leaves the drive unmonitored, `detail` reads it with another smartctl detail level, and `checks` overrides any check for that drive (FR-403).
- `pve-smart-alert config check` validates the whole file and exits non-zero on errors, which name the key and the line (FR-405). `pve-smart-alert config show` prints every key with its effective value and its origin, the file or the built-in default, and `--defaults` prints the built-in ones (FR-407).
- An invalid configuration file never stops a run: the last configuration that passed validation, saved as `last-good-config.json` in the state directory, or the built-in defaults are used and the error is reported (FR-406). An override that repeats the built-in default changes nothing.

### Changed

- `pve-smart-alert doctor` reports a configuration file that does not validate as a warning that says which configuration a run continues with, instead of failing: monitoring does not stop (FR-406).

[Unreleased]: https://github.com/florianpunz/pve-smart-alert/commits/main
