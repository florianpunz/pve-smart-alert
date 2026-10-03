# ADR 0002: Supported platforms and version baseline

- Status: Accepted
- Date: 2026-10-03

## Context

Every later decision depends on which Proxmox VE versions the tool must run on, because that fixes the available interpreter versions, the smartmontools version and the shape of the notification interface.

Facts on the decision date (see [research notes](../research/README.md)):

- Proxmox VE 9.2 is current (released 2026-05-21, Debian 13 "trixie").
- Proxmox VE 8 reached its end of life in 2026-08.
- Proxmox VE 9 ships smartmontools 7.4 (`7.4-pve1`) and, from Debian 13, Python 3.13.
- The notification interface used by this project has had its current shape since `pve-manager` 8.2.3 (June 2024).
- smartmontools has JSON output since 7.0.
- Proxmox VE is officially an amd64 product.

## Options considered

1. **Proxmox VE 9.x only.** One Debian release, one Python version, one smartmontools version. Smallest test matrix.
2. **Proxmox VE 8.4 and 9.x.** Doubles the test matrix for a release that is already out of support. The maintainer's test cluster cannot run both.
3. **Any Debian-based host**, including Proxmox Backup Server and plain Debian. Wider audience, but the notification integration is specific to Proxmox VE and would need a second code path with a different test environment.

## Decision

- **Supported: Proxmox VE 9.x.** "Supported" means tested on a real host before each release and covered by CI.
- **Not supported, not blocked: Proxmox VE 8.2.3 and later.** The package does not refuse to install there. Bugs that only occur on version 8 are fixed only if the fix is trivial.
- **Out of scope: everything else**, including Proxmox Backup Server and plain Debian.
- **Language baseline: Python 3.11.** The code must run on 3.11 (first version with `tomllib`) and is tested on 3.11, 3.13 and the newest released Python. This costs almost nothing and keeps the code independent of a single minor version.
- **smartmontools baseline: 7.0** as the hard minimum (JSON output). 7.4 is the version the checks are designed against. Values that only exist in newer versions are used when present and never required.
- **Architecture: `all`.** The package contains no compiled code.
- Dependencies are declared by capability, not by product version: the package depends on `python3`, `perl`, `smartmontools` and `libpve-notify-perl`. The last one is what ties it to Proxmox VE.

## Consequences

- The design may rely on systemd, on Debian 13 paths and on the notification interface as it exists in Proxmox VE 9.
- Users on Proxmox VE 8 can try the tool but get no promise.
- Proxmox VE 10 is expected with Debian 14. Nothing in the design should make that upgrade hard: no compiled extensions, no third-party Python packages, and the only contact with Proxmox VE internals is isolated in one small file ([ADR 0008](0008-notification-integration.md)).
- Supporting Proxmox Backup Server later would mean a second notification transport. The transport is an interface in the architecture for this reason.

## Revisit when

- A new major version of Proxmox VE is announced.
- Proxmox VE updates smartmontools to 7.5 or later, which would make vendor-neutral wear values available.
- There is demand for Proxmox Backup Server.
