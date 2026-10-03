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
make check         # everything CI runs: lint, format check, type check, repository checks, tests
make test          # tests only
make build         # wheel and sdist in dist/
```

`make check` creates the virtual environment on its own if it is missing, so a fresh clone needs only that one command. Use `make format` to apply the formatter.

The linter, the formatter and the type checker are configured in `pyproject.toml`. The type checker runs in strict mode and the code is fully annotated.

## Tests

- Tests never need root, a Proxmox VE host or real drives ([ADR 0016](docs/adr/0016-test-strategy.md)).
- Every check of the catalog and every rule of the notification policy needs a test.
- The path to smartctl and to the notify bridge is injectable for this reason. Tests that use it do not depend on what is installed on the machine.
- Run the full suite with `make test` before you open a pull request.

## Fixtures and test data

- **No real serial number or WWN is committed.** Fixtures are anonymized before they are added ([ADR 0016](docs/adr/0016-test-strategy.md)).
- Every fixture gets an entry in `tests/fixtures/SOURCES.md` with its origin and its license.
- Recordings contributed by users are welcome. Attach them to an issue; they are anonymized on the way in.
- Data taken from another project is marked in the file that contains it, and the notice of that project is kept in `THIRD-PARTY-NOTICES.md`.

## Commits and branches

- Default branch: `main`. Feature branches: `feature/<topic>`. Fixes: `fix/<topic>`.
- Commit messages are in the imperative, with an optional scope prefix, for example `parsers: handle a missing attribute table` or `docs: describe the configuration keys`.
- Keep a change focused. A parser change and its fixture belong in one commit; an unrelated cleanup does not.

## Documentation

- A decision that constrains the architecture, the user-visible behavior, the supported platforms or the license gets a record in `docs/adr/`. Accepted records are not rewritten; a changed decision gets a new record that supersedes the old one ([ADR 0001](docs/adr/0001-record-architecture-decisions.md)).
- A statement about Proxmox VE or smartmontools is verified in documentation or source code and cited, or it is marked as an assumption in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).
- `docs/check-catalog.md` and the definitions in `src/pve_smart_alert/checks/` must not diverge.
- Answers found for an open question move to the document they belong to, and the entry is removed from [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).

## Reporting bugs and security issues

Bugs and feature requests go to the issue tracker.
Security issues are not reported there; see [SECURITY.md](SECURITY.md).
