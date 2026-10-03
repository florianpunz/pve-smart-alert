# ADR 0013: Debian package with a one-command installation

- Status: Accepted
- Date: 2026-10-03

## Context

Goals set by the maintainer: installation with one command, no care afterwards, nothing changed on the host except the tool's own files, and survival of Proxmox VE upgrades.
The tool consists of a Python package, one Perl script, two template files, three systemd units, a configuration file and documentation ([ADR 0003](0003-implementation-language.md), [ADR 0006](0006-scheduling.md), [ADR 0008](0008-notification-integration.md)).
A cluster needs it on every node.

## Options considered

1. **Shell installer that copies files** to `/usr/local` and writes unit files, in the style of many community scripts.
   One command. But nothing tracks the files: upgrades and removal are scripts of their own, leftovers are likely, and dependencies are not declared.
2. **`pip` or `pipx`.**
   Not installed on a Proxmox VE host by default, discouraged for system Python on Debian, and it cannot install units, templates or a Perl script cleanly.
3. **A single-file Python archive (zipapp)** plus unit files.
   Easy to copy. Still needs an installer for everything around it.
4. **A Debian package (`.deb`)** published with each release.
   dpkg tracks every file, declares dependencies, handles configuration files on upgrade, enables units through standard maintainer snippets, and removes everything on purge. Proxmox VE administrators use `apt` daily.
5. **An APT repository** in addition to option 4.
   Upgrades arrive with normal system updates. Needs a signing key, hosting and key rotation.
6. **A container.**
   Needs raw device access and privileges, cannot call the host's notification module, and adds a runtime the host does not have.

## Decision

### Format and distribution

- The tool is shipped as **one Debian package**, `pve-smart-alert`, architecture `all`.
- It is built in CI from the tagged source and attached to the release on the code hosting platform together with a `SHA256SUMS` file.
- Each release also carries the package under a version-independent file name, so that a stable URL always points to the newest release.
- An **APT repository is planned after version 1.0** ([ROADMAP.md](../../ROADMAP.md)). Until then, upgrading means installing the newer package the same way.

### One command

Two equivalent forms are documented:

```sh
# Direct: download the newest package and install it with apt
wget -qO /tmp/pve-smart-alert.deb https://github.com/florianpunz/pve-smart-alert/releases/latest/download/pve-smart-alert.deb \
  && apt install -y /tmp/pve-smart-alert.deb

# Convenience script: same result, verifies the checksum, can pin a version
wget -qO- https://github.com/florianpunz/pve-smart-alert/releases/latest/download/install.sh | sh
```

`wget` is used because it is a dependency of `pve-manager` and therefore present on every Proxmox VE host.
The script does nothing except download, verify and call `apt install`. Everything that changes the system is done by the package, so the two forms cannot diverge.
On a cluster the command is run on each node.

### What the package installs

| Path | Content |
| --- | --- |
| `/usr/sbin/pve-smart-alert` | Launcher |
| `/usr/share/pve-smart-alert/pve_smart_alert/` | Python package, as source, without byte code |
| `/usr/libexec/pve-smart-alert/notify-bridge` | Perl bridge |
| `/usr/libexec/pve-smart-alert/report-failure` | Shell script used by the failure unit |
| `/usr/share/pve-manager/templates/default/pve-smart-alert-subject.txt.hbs`, `pve-smart-alert-body.txt.hbs` | Notification templates |
| `/usr/lib/systemd/system/pve-smart-alert.service`, `pve-smart-alert.timer`, `pve-smart-alert-failure.service` | Units |
| `/etc/pve-smart-alert/config.toml` | Configuration, marked as a configuration file |
| `/usr/share/doc/pve-smart-alert/` | Reference configuration, changelog, license |
| `/usr/share/man/man8/pve-smart-alert.8.gz` | Manual page |

Created at run time: `/var/lib/pve-smart-alert/` and `/run/pve-smart-alert/`.

### Dependencies

`Depends: python3 (>= 3.11), perl, smartmontools (>= 7.0), libpve-notify-perl`.
`libpve-notify-perl` is what restricts installation to Proxmox VE. Mail delivery needs no extra dependency: Proxmox VE itself depends on a mail transport agent and on `proxmox-mail-forward`.

### Maintainer scripts

- Only the standard debhelper snippets: enable and start the timer on installation, stop it on removal, reload systemd.
- On purge: remove `/var/lib/pve-smart-alert/` and `/etc/pve-smart-alert/`.
- No other action. In particular nothing in the maintainer scripts edits a foreign file, calls the network or sends a notification. The first check is started by the timer ([ADR 0006](0006-scheduling.md)), not by the package scripts.

### Upgrades of Proxmox VE

- Minor upgrades: nothing to do. The package has no version-specific paths except the template directory.
- Major upgrades: the package depends only on what the new release provides under the same names. The Python code has no compiled parts and no third-party modules. If the notification interface changes, the fallback transport takes over until a new release adapts the bridge ([ADR 0008](0008-notification-integration.md)).

## Consequences

- Installation, upgrade and removal are single `apt` commands with the behavior administrators expect, and `dpkg -L pve-smart-alert` shows every installed file.
- The release pipeline must build and test a Debian package. This is the main cost of the decision.
- Until the APT repository exists, new versions are not picked up by `apt upgrade`. The tool keeps working without upgrades; a release notes feed is the way to hear about new versions.
- Piping a script into a shell is a habit that deserves criticism. The direct form avoids it, and the script is short enough to read.
- The stable download URL depends on the hosting platform's "latest release" redirect. The platform is decided in [ADR 0019](0019-repository-hosting.md).
- Checksums protect against corrupted downloads, not against a compromised release. Signed packages come with the APT repository.

## Revisit when

- The APT repository is set up.
- The package is offered for inclusion in a community script collection, which may impose its own installer conventions.
