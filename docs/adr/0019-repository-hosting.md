# ADR 0019: Repository on GitHub under the maintainer's account

- Status: Accepted
- Date: 2026-10-03
- Decided by: the maintainer

## Context

The project needs a public home with git hosting, an issue tracker (also for contributed recordings, [ADR 0016](0016-test-strategy.md)), CI that can build and test a Debian package, and release downloads with a stable URL for the newest version ([ADR 0013](0013-packaging-and-installation.md)).

## Options considered

| Option | For | Against |
| --- | --- | --- |
| GitHub, personal account | Where the audience is: the comparable projects found during research are hosted there (Scrutiny, smartctl_exporter, check_smart, Pulse, the community scripts). Releases with a "latest" download URL. CI included. The maintainer has an account | Proprietary platform |
| GitHub, organization | As above, and easier to add maintainers later | One more thing to manage for a one-person project. A repository can be transferred to an organization later |
| Codeberg | Non-profit platform for free software | Smaller audience for this kind of tool |
| GitLab.com | CI included | Smaller audience for this kind of tool |
| Self-hosted | Full control | Operating effort, no audience |

## Decision

- The repository is **<https://github.com/florianpunz/pve-smart-alert>**.
- CI runs on GitHub Actions.
- Releases are GitHub releases with these assets: the versioned package, the same package under the fixed name `pve-smart-alert.deb`, `install.sh` and `SHA256SUMS`.
- Bugs, feature requests and contributed recordings go through the issue tracker.
- The installation command of [ADR 0013](0013-packaging-and-installation.md) therefore reads:

  ```sh
  wget -qO /tmp/pve-smart-alert.deb https://github.com/florianpunz/pve-smart-alert/releases/latest/download/pve-smart-alert.deb \
    && apt install -y /tmp/pve-smart-alert.deb
  ```

Editorial note: the placeholders for host and owner in ADR 0013 were filled in with these values, and its remark that the platform is undecided now points to this record. Nothing else in ADR 0013 changed.

## Consequences

- There is no public repository at this address yet. Creating it is part of milestone M0.
- The stable download URL relies on GitHub's redirect to the newest release.
- The project depends on one commercial platform for hosting, CI and distribution. The git history is portable; issues and release assets are less so. The APT repository planned after 1.0 can be hosted elsewhere.

## Revisit when

- A second maintainer joins.
- The APT repository is set up and needs a hosting decision of its own.
