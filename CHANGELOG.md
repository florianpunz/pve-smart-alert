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
- A Debian package with a launcher, the bridge, the templates and the configuration file; `make build` builds it together with the Python distribution ([ADR 0013](docs/adr/0013-packaging-and-installation.md)).

### Changed

- `pve-smart-alert test-notification` points out that an empty log can mean that no matcher matched.

[Unreleased]: https://github.com/florianpunz/pve-smart-alert/commits/main
