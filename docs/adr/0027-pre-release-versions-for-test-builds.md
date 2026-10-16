# ADR 0027: Pre-release versions for test builds

- Status: Accepted
- Date: 2026-10-16
- Decided by: the maintainer
- Extends: [ADR 0013](0013-packaging-and-installation.md)

## Context

The version of the program and of the package was raised once per milestone, when the milestone was accepted ([ADR 0013](0013-packaging-and-installation.md), `scripts/check_version_sync.py`).
Between two acceptances the content changes a lot, and test builds of it go to test hosts: the package of milestone M5 and of the first slices of M6 still said 0.4.0.

That is harmful in two ways. apt treats a package of the version that is installed as "already the newest version" and installs nothing, so a deploy can silently keep old code. And the upgrade step of the M5 acceptance, an upgrade that keeps configuration and state, cannot be tested between two builds of the same version.

0.5.0 is reserved for the release after the acceptance of M5, and its tag is not set before ([ROADMAP.md](../../ROADMAP.md)).

## Options considered

1. **Keep one version per milestone.** Has the two faults above.
2. **Raise the release number for every test build** (0.5.0, 0.5.1, ...). Spends the numbers of releases on builds that are never released.
3. **A local suffix such as `0.4.0+git20261016`.** Sorts after 0.4.0, but also after a later 0.4.1, and says nothing about the release it leads to.
4. **Pre-release versions of the next release: `0.5.0~devN`.** dpkg sorts `~` before everything, so `0.4.0 < 0.5.0~dev1 < 0.5.0~dev2 < ... < 0.5.0`.

## Decision

Option 4.

- Every build that goes to a test host is a pre-release of the next release, `X.Y.Z~devN` in the package and `X.Y.Z.devN` in the program (PEP 440 has no `~`; its `.devN` sorts the same way). The first is `0.5.0~dev1`.
- `N` is counted up by one for every such build, starting at 1 for each release. A build is not installed on a test host twice under the same version.
- `debian/changelog` gets a new entry and `src/pve_smart_alert/__init__.py` the same version in the same commit. `scripts/check_version_sync.py` accepts exactly this pair besides an identical release version, and nothing else.
- A pre-release is never tagged and never published. The release workflow refuses a tag whose version is a pre-release.
- The release itself, such as 0.5.0, drops the suffix after its acceptance, as before ([ADR 0013](0013-packaging-and-installation.md)).

Checked: `dpkg --compare-versions` and the version rules of PEP 440 sort 0.4.0, 0.5.0~dev1 and .dev1, ~dev2 and .dev2, ~dev10 and .dev10, and 0.5.0 in this order (2026-10-16).

## Consequences

- Every test build upgrades the one before it, and the upgrade path of the acceptance is tested with every build.
- `pve-smart-alert --version` of a test build says `0.5.0.dev1`, which tells at a glance that a host runs a pre-release.
- The counter is kept by hand in two files; the version check and CI catch a forgotten one.
- A test host that has a pre-release installed takes the release 0.5.0 as an upgrade.

## Revisit when

- An APT repository is set up after version 1.0 ([ADR 0013](0013-packaging-and-installation.md)) and needs another scheme for its builds.
