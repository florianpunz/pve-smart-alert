# ADR 0041: Normal versions for test builds

- Status: Accepted
- Date: 2026-11-03
- Decided by: the maintainer
- Supersedes: [ADR 0027](0027-pre-release-versions-for-test-builds.md)

## Context

[ADR 0027](0027-pre-release-versions-for-test-builds.md) numbered every build that went to a test host as a pre-release of the next release, `X.Y.Z~devN` in the package and `X.Y.Z.devN` in the program, so that apt installs each build over the one before it and the release drops the suffix after its acceptance. That scheme costs two spellings of the same version, an exception in the version check, a refusal of `.dev` tags in the release workflow, and a `--version` that does not read like the version of the package.

Since 0.5.1 is released and the test runs happen on one disposable host (`pve2`, [ROADMAP.md](../../ROADMAP.md), test environment), the maintainer decided on 2026-11-03 to go back to normal versions: every build carries a version `X.Y.Z` without a suffix, and a build that is accepted is the release.

## Options considered

1. **Keep the pre-release scheme.** Every cost above stays, and the release number of an accepted build still changes after its acceptance.
2. **Normal `X.Y.Z` versions for every build.** One spelling in both files, one rule in the version check, and a build that is accepted is tagged as the release without a change of its version. A rejected build spends its number.
3. **A local suffix such as `X.Y.Z+buildN`.** One spelling, but dpkg sorts it after `X.Y.Z`, so a build would outrank the release it belongs to.

## Decision

Option 2.

- Every build that goes to a test host carries the next patch version of the current line, `X.Y.Z`, the same in `debian/changelog` and in `src/pve_smart_alert/__init__.py`, in one commit with the new changelog entry. After 0.5.1 the first build is 0.5.2.
- A build is never put on a test host twice under one version.
- A build is not tagged. The version that the maintainer accepts is tagged as the release, and the tag names the build that ran on the host.
- No suffix form exists: `scripts/check_version_sync.py` requires the two files to name the same `X.Y.Z` and rejects a pre-release form such as `X.Y.Z.devN` or `X.Y.Z~devN`.
- `CHANGELOG.md` gets its section for a version when the version is released; every build gets its entry in `debian/changelog`.

## Consequences

- `pve-smart-alert --version` of a test build reads like a release; only the tag makes a release. A host that runs a build says a version that a later release may share, which is intended.
- A build that is accepted becomes the release without a version change, so the package a test host runs and the released package are the same file.
- Two files still have to be kept in step by hand; the version check and CI catch a forgotten one.
- The refusal of `.dev` tags in `.github/workflows/release.yml` and the rewrite in `.github/workflows/ci.yml` become dead code; they can go when those workflows are next touched.
- Historical entries that name `0.5.0~devN` builds stay as they are: they describe what ran at the time.

## Revisit when

- An APT repository is set up after version 1.0 ([ADR 0013](0013-packaging-and-installation.md)) and needs another scheme for its builds, or a build has to be told apart from a release on a host without its tag.
