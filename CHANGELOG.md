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

### Changed

- `pve-smart-alert test-notification` points out that an empty log can mean that no matcher matched.
- The wear value of an SSD is taken from the vendor-neutral sources first and from the vendor attribute of the Proxmox VE web interface last, and the source is shown ([ADR 0021](docs/adr/0021-wear-value-source.md)).
- The example matcher in the README routes all four severities of the tool.

[Unreleased]: https://github.com/florianpunz/pve-smart-alert/commits/main
