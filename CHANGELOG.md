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
- The wear value of an SSD comes from `endurance_used`, the device statistics or the NVMe health log, and only then from a vendor attribute, with its source, and the value the web interface shows is kept next to it ([ADR 0021](docs/adr/0021-wear-value-source.md)). For ATA, the value of `endurance_used` counts as the vendor-neutral source only when the device statistics were read; a guess of smartmontools without them is named as the vendor attribute it is ([Research 03](docs/research/03-smart-indicators.md)).
- `pve-smart-alert doctor` reports the route of the fallback in a line `fallback`: whether a matcher routes mail to root, which arrives as `system-mail`, and whether `/root/.forward` hands it to the notification system ([ADR 0022](docs/adr/0022-fallback-routing-check.md)).
- When a matcher would route a notification but it or its targets are disabled, `pve-smart-alert doctor` and `pve-smart-alert test-notification` name it instead of advising a new matcher.
- `pve-smart-alert check --dry-run` evaluates every drive against the checks of the [check catalog](docs/check-catalog.md) and prints the findings with their check, severity, value and threshold, and the notifications a run would send now; it sends nothing and changes no state (FR-601).
- The evaluation: a catalog of independent checks with stable identifiers, the drive's own failure verdict always critical, raw defect counters with thresholds from published failure rates, wear capped at warning, and missing data never a finding ([ADR 0010](docs/adr/0010-health-evaluation-and-default-thresholds.md)). The command timeouts of attribute 188 are read decoded where the drive packs them (Q-T1).
- The configuration accepts the global overrides of `[checks."<check-id>"]`: `enabled` and the thresholds `notice`, `warning` and `critical`, one number or, for the temperature, a table of the drive classes (FR-402).
- The configuration accepts per-drive overrides in `[[drive]]`, selected by model pattern, serial number or WWN: `exclude` leaves the drive unmonitored, `detail` reads it with another smartctl detail level, and `checks` overrides any check for that drive (FR-403).
- `pve-smart-alert config check` validates the whole file and exits non-zero on errors, which name the key and the line (FR-405). `pve-smart-alert config show` prints every key with its effective value and its origin, the file or the built-in default, and `--defaults` prints the built-in ones (FR-407).
- An invalid configuration file never stops a run: the last configuration that passed validation, saved as `last-good-config.json` in the state directory, or the built-in defaults are used and the error is reported (FR-406). An override that repeats the built-in default changes nothing.
- `pve-smart-alert check` runs one check and sends the notifications that are due, following the policy of [ADR 0009](docs/adr/0009-notification-policy.md): a problem once, again when its severity rises, when its value worsens after a cool-down, and as a reminder per severity; a recovery when it has cleared; one message per drive and one summary above the grouping limit; one summary on the first run (FR-509 to FR-516). A notification that is not handed over is planned again on the next run (FR-517). Each run logs one summary line (FR-606), and a second run while one holds the lock exits with status 3 (FR-605).
- The state of the tool is kept in `/var/lib/pve-smart-alert/state.json`, replaced atomically; a corrupt file is set aside and the next notification is one summary ([ADR 0007](docs/adr/0007-state-storage.md), NFR-11, NFR-12).
- The event checks `ata.crc_errors`, `ata.error_log`, `nvme.thermal_excursion` and `nvme.error_log` report a rise of their counter above the baseline of the state; the value a drive has when it is first seen never alerts (FR-306).
- A drive that is absent for two runs is reported as missing, once, and one without usable data for two runs as unreadable (FR-309, FR-310). Both are checks of the catalog, `drive.missing` and `drive.unreadable`, and can be switched off.
- Problems of the tool itself are notified under the same policy: smartctl missing or too old, a failed device scan, an invalid configuration, a notify bridge that cannot be used, and a state file that was reset (FR-518).
- The configuration accepts the settings of the notification policy in `[notify]` and `[notify.reminder]`, and the confirmation count `confirm_runs` of a condition check (FR-404).
- `pve-smart-alert status` shows the last run and every drive with its active conditions from the state, and `--json` prints the state (FR-602).
- `pve-smart-alert doctor` reports the state file and the last run in a line `state`.

- The package installs a systemd timer that runs `pve-smart-alert check` 3 minutes after boot and then every 30 minutes, and enables it; installing the package starts the first check ([ADR 0006](docs/adr/0006-scheduling.md)). A run that fails sends a short mail to root, at most once per day, through a script that does not use the code of the tool (FR-519).

- `pve-smart-alert doctor` reports the timer with its interval and next run, the version of Proxmox VE, and whether smartd is active and mails root, which reports some problems twice; the README says how to quiet smartd by hand (FR-603, [ADR 0012](docs/adr/0012-read-only-and-coexistence-with-smartd.md)).

### Changed

- `pve-smart-alert doctor` reports a configuration file that does not validate as a warning that says which configuration a run continues with, instead of failing: monitoring does not stop (FR-406).

### Fixed

- `pve-smart-alert config check` names the line of an unknown check identifier, as it does for every other configuration error (FR-405).
- The wear of an ATA drive read with `smartctl.detail = "basic"` no longer claims the vendor-neutral source: without the device statistics, smartmontools guesses `endurance_used` from a vendor attribute, and the guess is shown as the vendor attribute it is.
- A run with an invalid configuration and no last good configuration says that the built-in defaults are in use, instead of claiming a last good configuration (FR-406).

[Unreleased]: https://github.com/florianpunz/pve-smart-alert/commits/main
