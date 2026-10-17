# Contributing

Thanks for looking at PVE SMART Alert. This document describes how to work in this repository.
Read [CLAUDE.md](CLAUDE.md) first: it contains the binding rules, and they apply to human contributors as well.

## Rules that apply to every contribution

- **Everything is in English**: code, comments, documentation, commit messages, branch names, configuration keys, log messages and notification texts.
- **No AI attribution.** No `Co-Authored-By` trailer naming an AI tool, no "Generated with ..." line, no session links, in commits, pull requests or files. A check in CI enforces this for the repository content.
- **Every source file starts with an SPDX license identifier**, for example `# SPDX-License-Identifier: AGPL-3.0-or-later`. The check in CI knows the file types that are expected to carry one.
- **Contributions come in under the license of the project**, AGPL-3.0-or-later. There is no contributor license agreement: inbound equals outbound ([ADR 0015](docs/adr/0015-license.md)).
- **No third-party Python package at run time.** The installed tool uses the standard library only. Development tools are fine ([ADR 0003](docs/adr/0003-implementation-language.md)).
- **The tool is read-only.** Nothing is changed on the host except the tool's own files, and no command is sent to a drive that changes it ([ADR 0012](docs/adr/0012-read-only-and-coexistence-with-smartd.md)).
- **Identifiers are stable.** Requirement IDs, check IDs, configuration keys, notification fields and command names are public interface ([ADR 0010](docs/adr/0010-health-evaluation-and-default-thresholds.md), [ADR 0014](docs/adr/0014-repository-structure.md)).

## Development setup

Requirements: Python 3.11 or later, GNU Make and git. Nothing else has to be installed.

```sh
make dev-install   # creates .venv and installs the linter, the type checker, pytest and the build tool
make check         # what CI checks on every Python version: lint, format check, type check, repository checks, tests
make test          # tests only
make build         # the Debian package and the Python distribution
make deb           # the Debian package in dist/ (needs build-essential, dpkg-dev and debhelper)
make python-dist   # wheel and sdist in dist/
```

`make check` creates the virtual environment on its own if it is missing, so a fresh clone needs only that one command. Use `make format` to apply the formatter.

The linter, the formatter and the type checker are configured in `pyproject.toml`. The type checker runs in strict mode and the code is fully annotated.

## Tests

- Tests never need root, a Proxmox VE host or real drives ([ADR 0016](docs/adr/0016-test-strategy.md)).
- Every check of the catalog and every rule of the notification policy needs a test.
- The path to smartctl and to the notify bridge is injectable for this reason. Tests that use it do not depend on what is installed on the machine.
- `tests/guard.py` makes this a rule of the test frame: every program the tool starts goes through `pve_smart_alert.process`, and in a test it may come only from the test tree, such as `tests/fake-smartctl`, or from the temporary directory of pytest, where a test writes its stand-ins for lsblk, pvesh, sendmail and the notify bridge. A test that would start the smartctl, lsblk, pvesh or notify bridge of the machine fails and names the program, also when the tool catches the error. Only the tests of the process runner start programs of the machine on purpose; they carry the marker `real_programs`. `tests/unit/test_test_frame.py` shows that the guard stops a misconfigured test.
- Run the full suite with `make test` before you open a pull request.

## The Debian package

- `debian/` maps the repository to the installed paths and holds nothing else. Which file ends up where is in `debian/pve-smart-alert.install` and in [ARCHITECTURE.md](ARCHITECTURE.md) section 12; the package installs one file per entry and touches no file of another package ([ADR 0012](docs/adr/0012-read-only-and-coexistence-with-smartd.md), [ADR 0013](docs/adr/0013-packaging-and-installation.md)).
- The Python package is installed as source under `/usr/share/pve-smart-alert` and imported from there by the launcher. Nothing is byte-compiled: `/usr` belongs to dpkg, and a `.pyc` file written at run time would belong to no package.
- The maintainer scripts do nothing but the standard debhelper snippets, and `purge` removes the configuration, the state and the runtime directory of the tool. Nothing else.
- The units live in `systemd/` and are installed by the install list. `debian/rules` hands only the timer to `dh_installsystemd`: unnamed, it would also write start snippets for the two services, and the installation would run a check by itself ([ARCHITECTURE.md](ARCHITECTURE.md) section 13). A new unit that the maintainer scripts must enable or start has to be named there.
- The version of the package is the version of the program. `make hygiene` compares `src/pve_smart_alert/__init__.py` with the newest entry of `debian/changelog`, so a release changes both in one commit.
- Every build that goes to a test host is a pre-release of the next release ([ADR 0027](docs/adr/0027-pre-release-versions-for-test-builds.md)): `0.5.0~devN` in `debian/changelog` and `0.5.0.devN` in `src/pve_smart_alert/__init__.py`, with `N` counted up by one for each such build, in one commit with a new changelog entry. apt installs nothing over a package of the same version, so a build is never put on a test host twice under one version. A pre-release is never tagged; the release drops the suffix after its acceptance.
- Building the package needs `build-essential`, `dpkg-dev` and `debhelper`: `make deb`, or `make build` for the package and the Python distribution together. It runs in CI and on a Debian or Proxmox VE host, not on every development machine.
- CI builds the package on every push and inspects it: the file list, the dependencies, that the shipped configuration is a conffile, that the source tree ends up where the launcher looks for it, that no byte code is inside, that the maintainer scripts act on the timer and on no service, and that `systemd-analyze verify` reads the units without a complaint, a warning included. It plants a `__pycache__` directory in the source tree before the build, so that the exclusion is exercised instead of assumed. Then it runs lintian, and an error from lintian fails the job. Last, `scripts/package-test.sh` installs the package in a clean `debian:trixie` container with the Proxmox VE package repository, checks the installed files, runs the tool, purges the package and checks that nothing is left.
- A release is a tag `v<version>` on `main`, pushed after the commit that sets the version in `src/pve_smart_alert/__init__.py` and `debian/changelog` and renames the section `[Unreleased]` of `CHANGELOG.md` to `[<version>]`. `.github/workflows/release.yml` runs the checks of CI, refuses a tag that is not the version or a version without a section in the changelog, builds and tests the package again, and publishes it as `pve-smart-alert_<version>_all.deb` and as `pve-smart-alert.deb`, together with `install.sh` and `SHA256SUMS`. The stable name is what the one-command installation downloads.

## Fixtures and test data

- **No real serial number or WWN is committed.** Fixtures are anonymized before they are added ([ADR 0016](docs/adr/0016-test-strategy.md)), and a test checks every fixture for it.
- Recorded fixtures are written by `scripts/make_fixtures.py` from an archive of `scripts/collect-node-data.sh`, never by hand. It replaces serial numbers, WWNs, EUI-64s, the logical unit ids and SAS addresses of SCSI drives with placeholders and writes nothing if a real value is left ([ADR 0023](docs/adr/0023-anonymization-of-recordings.md), [ADR 0026](docs/adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)). Keep the archives themselves out of the repository.
- Test data of another project becomes a fixture through `scripts/make_fixtures.py import`, only under a license compatible with AGPL-3.0-or-later, from a pinned commit, and with the license text of the source in `tests/fixtures/licenses/` ([ADR 0026](docs/adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)). Output quoted in an issue or a forum is evidence for a research note, not a fixture.
- Every fixture gets an entry in `tests/fixtures/SOURCES.md` with its origin and its license.
- A change to the text or the fields of a notification updates its golden file in `tests/fixtures/golden/`: `PVE_SMART_ALERT_UPDATE_GOLDEN=1 make test` rewrites them, and the diff belongs to the change.
- A host whose drives change from run to run is a scenario in `tests/scenarios.py`: a base recording and the edits of each step. The scenario tests run the program once per step with the clock, the state directory and the transport of `tests/unit/frame.py`.
- Recordings contributed by users are welcome, above all of the controllers that [docs/hardware-support.md](docs/hardware-support.md) labels "Experimental" or lists as not known yet, and of `mpi3mr` in HBA personality (Q-R7): MegaRAID with SAS drives, HPE Smart Array with `hpsa` or `smartpqi`, Adaptec, Areca, `mpi3mr` in HBA personality, and NVMe drives behind a tri-mode controller. Record the host with `pve-smart-alert dump-fixture --all`, as that document describes, look at the archive, and attach it to an issue with the drivers of the SCSI hosts and the controller model. A recording comes into the project under AGPL-3.0-or-later, like every contribution; it is checked for identifiers again on the way in.
- Data taken from another project is marked in the `recording.json` of its fixture, and the project is listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) and in `debian/copyright`.

## Commits and branches

- Default branch: `main`. Feature branches: `feature/<topic>`. Fixes: `fix/<topic>`.
- A commit message starts with the type of the change, a colon and a summary in the imperative, in lowercase and without a scope: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `build:`, `ci:` or `chore:`, for example `feat: add the drive model` or `docs: describe the configuration keys`. Where the summary is not enough, a body says what changed and why.
- Keep a change focused. A parser change and its fixture belong in one commit; an unrelated cleanup does not.

## Documentation

- Keeping the documents current is part of every change: [Documentation upkeep](CLAUDE.md#documentation-upkeep) in CLAUDE.md says which document holds what.
- A decision that constrains the architecture, the user-visible behavior, the supported platforms or the license gets a record in `docs/adr/`. Accepted records are not rewritten; a changed decision gets a new record that supersedes the old one ([ADR 0001](docs/adr/0001-record-architecture-decisions.md)).
- A statement about Proxmox VE or smartmontools is verified in documentation or source code and cited, or it is marked as an assumption in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).
- `docs/check-catalog.md` and the definitions in `src/pve_smart_alert/checks/` must not diverge.
- Answers found for an open question move to the document they belong to, and the entry is removed from [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).

## Reporting bugs and security issues

Bugs and feature requests go to the issue tracker.
Security issues are not reported there; see [SECURITY.md](SECURITY.md).
